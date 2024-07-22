import json
import asyncio
import threading
from queue import PriorityQueue

import tornado.ioloop
import tornado.netutil
import tornado.process
import tornado.httpserver
import tornado.web
import tornado.log
import tornado.options
import tornado.websocket

import utils
import config
import executor_server
from stdchal import StdChal

class ChalObj:
    def __init__(self, chal, callback_func):
        self.chal = chal
        self.callback_func = callback_func

    def __lt__(self, other):
        return self.chal['chal_id'] < other.chal['chal_id']

class JudgeDispatcher:
    judge_usage = 0
    chal_running_count = 0
    chal_queue = PriorityQueue()
    event = threading.Event()

    @staticmethod
    def start_chal(obj):
        chal_id = obj['chal_id']
        code_path = obj['code_path']
        res_path = obj['res_path']
        test_list = obj['test']
        metadata = obj['metadata']
        comp_type = obj['comp_type']
        check_type = obj['check_type']

        test_paramlist = []
        assert comp_type in ['gcc', 'g++', 'clang', 'clang++', 'makefile', 'python3', 'rustc', 'java']
        assert check_type in ['diff', 'ioredir', 'diff-strict']

        memlimit, timelimit = 0, 0
        for test in test_list:
            memlimit = test['memlimit']
            timelimit = test['timelimit']

            data_ids = test['metadata']['data']
            t = []
            for data_id in data_ids:
                t.append({
                    'in': f"{res_path}/testdata/{data_id}.in",
                    'ans': f"{res_path}/testdata/{data_id}.out",
                    'timelimit': timelimit * 10 ** 6, # INFO: toj 的時間是ms，所以要乘上10^6
                    'memlimit': memlimit,
                })

            test_paramlist.append(t)

        chal = StdChal(chal_id, code_path, comp_type, check_type, res_path, test_paramlist, metadata)

        result = chal.start()
        res = {
            'chal_id': chal_id,
            'results': result
        }
        JudgeDispatcher.chal_running_count -= 1
        return res

    @staticmethod
    def running(loop):
        while JudgeDispatcher.event.wait():
            while not JudgeDispatcher.chal_queue.empty() and JudgeDispatcher.chal_running_count < config.JUDGE_TASK_MAXCONCURRENT:
                pri, chal_obj = JudgeDispatcher.chal_queue.get()
                chal, callback_func = chal_obj.chal, chal_obj.callback_func
                JudgeDispatcher.chal_running_count += 1

                def run():
                    results = JudgeDispatcher.start_chal(chal)
                    loop.add_callback(lambda: callback_func(results))

                t = threading.Thread(target=run)
                t.start()

            if JudgeDispatcher.chal_queue.empty():
                JudgeDispatcher.event.clear()

    @staticmethod
    def emit_chal(obj, callback_func):
        pri = obj['pri']
        if obj is not None:
            JudgeDispatcher.chal_queue.put((pri, ChalObj(obj, callback_func)))

        JudgeDispatcher.event.set()


class JudgeWebSocketClient(tornado.websocket.WebSocketHandler):
    async def open(self):
        utils.logger.info('Backend connected')

    async def on_message(self, msg):
        obj = json.loads(msg)

        JudgeDispatcher.emit_chal(obj, lambda res: self.write_message(json.dumps(res)))

    async def on_close(self):
        utils.logger.info('Backend disconnected')

    def check_origin(self, _: str) -> bool:
        return True

class MonitorWebSocketClient(tornado.websocket.WebSocketHandler):
    """
    Monitor
    """
    async def open(self):
        pass

    async def on_message(self, msg):
        pass

    async def on_close(self):
        pass

    def check_origin(self, _: str) -> bool:
        return True

class InfoRequestHandler(tornado.web.RequestHandler):
    """
    放一些info的地方，如Setting Version
    """

    async def get(self):
        pass

def init_socket_server():
    app = tornado.web.Application([
        (r"/judge", JudgeWebSocketClient),
        (r"/monitor", MonitorWebSocketClient),
        (r"/info", InfoRequestHandler),
    ])
    app.listen(2502)

def main():
    utils.logger.info("Judge Start")
    executor_server.init()
    err = executor_server.init_container({
        "cinitPath": "./cinit",
        "parallelism": 4
    })
    if err:
        utils.logger.error("Failed to init container")
        return

    init_socket_server()

    loop = tornado.ioloop.IOLoop.current()
    t = threading.Thread(target=JudgeDispatcher.running, args=(loop, ))
    t.start()
    loop.start()

if __name__ == "__main__":
    main()
