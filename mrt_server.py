# mrt_server.py
import socket
import threading
import time
from segment import Segment

class Server:
    def init(self, src_port, receive_buffer_size, bind_addr="127.0.0.1"):
        if (not isinstance(receive_buffer_size, int) or isinstance(receive_buffer_size, bool)
                or not 0 < receive_buffer_size <= 65535):
            raise ValueError("receive_buffer_size must be an integer between 1 and 65535 bytes")
        self.src_port = src_port
        self.receive_buffer_size = receive_buffer_size
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((bind_addr, self.src_port))
            self.src_port = self.sock.getsockname()[1]
            self.sock.settimeout(0.1)
            self.log_file = open(f"log_{self.src_port}.txt", "w")
        except BaseException:
            # No worker owns the socket until all acquisition steps succeed.
            try:
                self.sock.close()
            except OSError:
                pass  # Keep the original initialization failure.
            raise
        self.receive_buffer = []
        self.data_buffer = bytearray()
        self.state = "LISTEN"
        self._connection_established = False
        self.client_addr = None
        self.running = True
        self.expected_seq = 0
        self.lock = threading.Lock()
        self.rcv_thread = threading.Thread(target=self.rcv_handler)
        self.rcv_thread.start()
        self.sgmnt_thread = threading.Thread(target=self.sgmnt_handler)
        self.sgmnt_thread.start()

    def rcv_handler(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
                if len(data) < Segment.HEADER_SIZE or len(data) > 2048:
                    continue
                with self.lock:
                    self.receive_buffer.append((data, addr))
            except socket.timeout:
                continue

    def sgmnt_handler(self):
        while self.running:
            data_to_process = None
            with self.lock:
                if self.receive_buffer:
                    data_to_process, addr = self.receive_buffer.pop(0)
            
            if data_to_process:
                seg = Segment.deserialize(data_to_process)
                
                if seg.is_corrupt():
                    # log
                    self.log_file.write("rcv corrupt\n")
                    self.log_file.flush()
                    continue 
                else:
                    self.log_file.write(f"rcv {seg.seq_num} {seg.ack_num} {seg.flags} {seg.window}\n")
                    self.log_file.flush()
                    #

                with self.lock:
                    if self.client_addr is not None and addr != self.client_addr:
                        continue
                    current_window = max(0, self.receive_buffer_size - len(self.data_buffer))
                    
                    if self.state == "LISTEN" and (seg.flags & Segment.SYN):
                        self.client_addr = addr
                        self.state = "SYN_RCVD"
                        syn_ack_seg = Segment(flags=Segment.SYN | Segment.ACK, window=current_window)
                        self.sock.sendto(syn_ack_seg.serialize(), self.client_addr)
                        # log
                        self.log_file.write(f"snd {syn_ack_seg.seq_num} {syn_ack_seg.ack_num} {syn_ack_seg.flags} {syn_ack_seg.window}\n")
                        self.log_file.flush()
                        #
                    
                    elif self.state == "SYN_RCVD":
                        if (seg.flags & Segment.SYN):
                            syn_ack_seg = Segment(flags=Segment.SYN | Segment.ACK, window=current_window)
                            self.sock.sendto(syn_ack_seg.serialize(), self.client_addr)
                            self.log_file.write(f"snd {syn_ack_seg.seq_num} {syn_ack_seg.ack_num} {syn_ack_seg.flags} {syn_ack_seg.window}\n")
                            self.log_file.flush()
                        elif (seg.flags & (Segment.ACK | Segment.DAT | Segment.FIN)):
                            # Data or FIN also confirms receipt of our SYN-ACK
                            # when the final handshake ACK was lost.
                            self.state = "ESTABLISHED"
                            self._connection_established = True
                    
                    if self.state == "ESTABLISHED" and (seg.flags & Segment.DAT):
                        # only accept if expected sequence AND within window size
                        if seg.seq_num == self.expected_seq and len(seg.data) <= current_window:
                            self.data_buffer.extend(seg.data)
                            self.expected_seq += len(seg.data)
                        current_window = max(0, self.receive_buffer_size - len(self.data_buffer))
                            
                        ack_seg = Segment(ack_num=self.expected_seq, flags=Segment.ACK, window=current_window)
                        self.sock.sendto(ack_seg.serialize(), self.client_addr)
                        # log
                        self.log_file.write(f"snd {ack_seg.seq_num} {ack_seg.ack_num} {ack_seg.flags} {ack_seg.window}\n")
                        self.log_file.flush()
                        #
                        
                    elif self.state in ("ESTABLISHED", "CLOSED") and (seg.flags & Segment.FIN):
                        self.state = "CLOSED"
                        ack_seg = Segment(flags=Segment.ACK, window=current_window)
                        self.sock.sendto(ack_seg.serialize(), self.client_addr)
                        # log
                        self.log_file.write(f"snd {ack_seg.seq_num} {ack_seg.ack_num} {ack_seg.flags} {ack_seg.window}\n")
                        self.log_file.flush()
                        #
                    elif self.state == "FIN_WAIT" and (seg.flags & Segment.ACK):
                        self.state = "CLOSED"

            else:
                time.sleep(0.01)

    def accept(self):
        while True:
            with self.lock:
                # The peer may finish before the application is scheduled;
                # preserve its established connection and buffered bytes/EOF.
                if self._connection_established:
                    break
            time.sleep(0.01)
        return self.client_addr

    def receive(self, conn, length):
        accumulated_data = bytearray()
        
        while len(accumulated_data) < length:
            with self.lock:
                if self.state == "CLOSED" and not self.data_buffer:
                    break
                    
                if self.data_buffer:
                    remaining = length - len(accumulated_data)
                    read_len = min(remaining, len(self.data_buffer))
                    accumulated_data.extend(self.data_buffer[:read_len])
                    self.data_buffer = self.data_buffer[read_len:]
                    
                    # Buffer space freed! Send a Window Update ACK to the client
                    current_window = max(0, self.receive_buffer_size - len(self.data_buffer))
                    ack_seg = Segment(ack_num=self.expected_seq, flags=Segment.ACK, window=current_window)
                    self.sock.sendto(ack_seg.serialize(), self.client_addr)
                    
                    # log
                    self.log_file.write(f"snd {ack_seg.seq_num} {ack_seg.ack_num} {ack_seg.flags} {ack_seg.window}\n")
                    self.log_file.flush()
                    
            time.sleep(0.01)
            
        return bytes(accumulated_data)

    def close(self):
        with self.lock:
            if self.state == "ESTABLISHED" and self.client_addr:
                self.state = "FIN_WAIT"
                fin_seg = Segment(flags=Segment.FIN)
                self.sock.sendto(fin_seg.serialize(), self.client_addr)
                self.log_file.write(f"snd {fin_seg.seq_num} {fin_seg.ack_num} {fin_seg.flags} {fin_seg.window}\n")
                self.log_file.flush()
                
        start_time = time.time()
        while self.state != "CLOSED" and time.time() - start_time < 2.0:
            time.sleep(0.01)
            
        self.running = False
        self.rcv_thread.join()
        if hasattr(self, 'sgmnt_thread'):
            self.sgmnt_thread.join()
        self.sock.close()
        self.log_file.close()
