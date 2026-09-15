# mrt_client.py
import socket
import threading
import time
from segment import Segment
from timer import Timer

class Client:
    def init(self, src_port, dst_addr, dst_port, segment_size):
        self.src_port = src_port
        self.dst_addr = dst_addr
        self.dst_port = dst_port
        self.segment_size = segment_size
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('', self.src_port))
        self.sock.settimeout(0.1) 
        
        self.state = "CLOSED"
        self.running = True
        
        self.seq_num = 0
        self.base_seq_num = 0
        self.send_window_size = 2048 
        self.unacked_segments = {} 
        self.timer = Timer(0.5)
        
        self.lock = threading.Lock()
        
        self.log_file = open(f"log_{self.src_port}.txt", "w") # log

        self.rcv_thread = threading.Thread(target=self.rcv_and_sgmnt_handler)
        self.rcv_thread.start()

    def rcv_and_sgmnt_handler(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(self.segment_size)
                seg = Segment.deserialize(data)

                # log
                if seg.is_corrupt():
                    self.log_file.write("rcv corrupt\n")
                    self.log_file.flush()
                else:
                    self.log_file.write(f"rcv {seg.seq_num} {seg.ack_num} {seg.flags} {seg.window}\n")
                    self.log_file.flush()
                #
                
                if seg.is_corrupt():
                    continue 
                
                with self.lock:
                    if self.state == "SYN_SENT" and (seg.flags & Segment.SYN) and (seg.flags & Segment.ACK):
                        self.state = "ESTABLISHED"
                        self.timer.stop()
                        self.send_window_size = seg.window # Update window from server
                        ack_seg = Segment(flags=Segment.ACK)
                        self.sock.sendto(ack_seg.serialize(), (self.dst_addr, self.dst_port))
                        # log
                        self.log_file.write(f"snd {ack_seg.seq_num} {ack_seg.ack_num} {ack_seg.flags} {ack_seg.window}\n")
                        self.log_file.flush()
                        #
                    
                    elif self.state == "ESTABLISHED" and (seg.flags & Segment.ACK):
                        self.send_window_size = seg.window # Update window size
                        
                        # ACK logic
                        if seg.ack_num > self.base_seq_num:
                            self.base_seq_num = seg.ack_num
                            # Remove all acknowledged segments from unacked dict
                            keys_to_remove = [k for k in self.unacked_segments if k < self.base_seq_num]
                            for k in keys_to_remove:
                                del self.unacked_segments[k]
                            
                            if not self.unacked_segments:
                                self.timer.stop()
                            else:
                                self.timer.start() # Restart timer for oldest unacked

                    elif self.state == "ESTABLISHED" and (seg.flags & Segment.FIN):
                        self.state = "CLOSED"
                        ack_seg = Segment(flags=Segment.ACK)
                        self.sock.sendto(ack_seg.serialize(), (self.dst_addr, self.dst_port))
                        self.log_file.write(f"snd {ack_seg.seq_num} {ack_seg.ack_num} {ack_seg.flags} {ack_seg.window}\n")
                        self.log_file.flush()
                            
                    elif self.state == "FIN_WAIT" and (seg.flags & Segment.ACK):
                        self.state = "CLOSED"
                        self.timer.stop()
                        
            except socket.timeout:
                pass
            
            # Check for timeouts in handler thread
            with self.lock:
                if self.state in ["ESTABLISHED", "SYN_SENT", "FIN_WAIT"] and self.timer.timeout():
                    if self.state == "ESTABLISHED" and self.unacked_segments:
                        # GBN
                        oldest_seq = min(self.unacked_segments.keys())
                        seg_bytes = self.unacked_segments[oldest_seq]
                        self.sock.sendto(seg_bytes, (self.dst_addr, self.dst_port))
                        # log
                        re_seg = Segment.deserialize(seg_bytes)
                        self.log_file.write(f"snd {re_seg.seq_num} {re_seg.ack_num} {re_seg.flags} {re_seg.window}\n")
                        self.log_file.flush()
                        #
                    elif self.state == "SYN_SENT":
                        syn_seg = Segment(flags=Segment.SYN)
                        self.sock.sendto(syn_seg.serialize(), (self.dst_addr, self.dst_port))
                        # log
                        self.log_file.write(f"snd {syn_seg.seq_num} {syn_seg.ack_num} {syn_seg.flags} {syn_seg.window}\n")
                        self.log_file.flush()
                        #
                    elif self.state == "FIN_WAIT":
                        fin_seg = Segment(flags=Segment.FIN)
                        self.sock.sendto(fin_seg.serialize(), (self.dst_addr, self.dst_port))
                        # log
                        self.log_file.write(f"snd {fin_seg.seq_num} {fin_seg.ack_num} {fin_seg.flags} {fin_seg.window}\n")
                        self.log_file.flush()
                        #
                    self.timer.start()

    def connect(self):
        with self.lock:
            self.state = "SYN_SENT"
            syn_seg = Segment(flags=Segment.SYN)
            self.sock.sendto(syn_seg.serialize(), (self.dst_addr, self.dst_port))
            # log
            self.log_file.write(f"snd {syn_seg.seq_num} {syn_seg.ack_num} {syn_seg.flags} {syn_seg.window}\n")
            self.log_file.flush()
            #
            self.timer.start()
        
        while True:
            with self.lock:
                if self.state == "ESTABLISHED":
                    break
            time.sleep(0.01)

    def send(self, data):
        payload_size = self.segment_size - Segment.HEADER_SIZE
        i = 0
        
        while i < len(data):
            sent_this_round = False
            with self.lock:
                # send only if within window
                if (self.seq_num - self.base_seq_num) + payload_size <= self.send_window_size:
                    chunk = data[i:i+payload_size]
                    seg = Segment(seq_num=self.seq_num, flags=Segment.DAT, data=chunk)
                    seg_bytes = seg.serialize()
                    
                    self.unacked_segments[self.seq_num] = seg_bytes
                    self.sock.sendto(seg_bytes, (self.dst_addr, self.dst_port))
                    # log
                    self.log_file.write(f"snd {seg.seq_num} {seg.ack_num} {seg.flags} {seg.window}\n")
                    self.log_file.flush()
                    #
                    
                    if not self.timer.is_running:
                        self.timer.start()
                        
                    self.seq_num += len(chunk)
                    i += len(chunk)
                    sent_this_round = True
            
            # yield lock ONLY if the window was full and we couldn't send
            if not sent_this_round:
                time.sleep(0.001)

        # deny until all ACKed
        while True:
            with self.lock:
                if not self.unacked_segments:
                    break
            time.sleep(0.01)

    def close(self):
        with self.lock:
            self.state = "FIN_WAIT"
            fin_seg = Segment(flags=Segment.FIN)
            self.sock.sendto(fin_seg.serialize(), (self.dst_addr, self.dst_port))
            # log
            self.log_file.write(f"snd {fin_seg.seq_num} {fin_seg.ack_num} {fin_seg.flags} {fin_seg.window}\n")
            self.log_file.flush()
            #
            self.timer.start()
        
        while True:
            with self.lock:
                if self.state == "CLOSED":
                    break
            time.sleep(0.01)
        self.running = False
        self.rcv_thread.join()

        self.log_file.close() # log



