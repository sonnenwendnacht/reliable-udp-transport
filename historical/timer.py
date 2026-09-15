# timer.py
import time

class Timer:
    def __init__(self, duration=0.5):
        self.duration = duration
        self.start_time = None
        self.is_running = False

    def start(self):
        self.start_time = time.time()
        self.is_running = True

    def stop(self):
        self.is_running = False

    def timeout(self):
        if not self.is_running:
            return False
        return time.time() - self.start_time>=self.duration