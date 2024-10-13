import json
import asyncio
import threading
from queue import Queue

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

class ChalPriority:
    NORMAL = 0
    CONTEST = 1
    CONTEST_REJUDGE = 2
    NORMAL_REJUDGE = 3

class JudgeDispatcher:
    judge_usage = 0
    chal_running_count = 0
    chal_queues = [Queue() for i in range(4)]
    chal_set = set()
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
        assert check_type in ['diff', 'ioredir', 'diff-strict', 'cms']

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
        JudgeDispatcher.chal_set.remove(chal_id)
        return res

    @staticmethod
    def running(loop):
        while JudgeDispatcher.event.wait():
            all_clear = True
            for idx, queue in enumerate(JudgeDispatcher.chal_queues):
                if queue.empty():
                    continue

                all_clear = False

                max_cnt = config.JUDGE_TASK_MAXCONCURRENT
                if idx == ChalPriority.CONTEST_REJUDGE or idx == ChalPriority.NORMAL_REJUDGE:
                    max_cnt -= 1

                while not queue.empty() and JudgeDispatcher.chal_running_count < max_cnt:
                    chal_obj = queue.get()
                    chal, callback_func = chal_obj.chal, chal_obj.callback_func
                    JudgeDispatcher.chal_running_count += 1

                    def run():
                        results = JudgeDispatcher.start_chal(chal)
                        loop.add_callback(lambda: callback_func(results))

                    t = threading.Thread(target=run)
                    t.start()

            if all_clear:
                JudgeDispatcher.event.clear()

    @staticmethod
    def emit_chal(obj, callback_func):
        pri = obj['pri']
        assert ChalPriority.NORMAL <= pri <= ChalPriority.NORMAL_REJUDGE
        if obj is not None and obj['chal_id'] not in JudgeDispatcher.chal_set:
            JudgeDispatcher.chal_set.add(obj['chal_id'])
            JudgeDispatcher.chal_queues[pri].put(ChalObj(obj, callback_func))

        JudgeDispatcher.event.set()


class JudgeWebSocketClient(tornado.websocket.WebSocketHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings['websocket_ping_interval'] = 5

    async def open(self):
        utils.logger.info('Backend connected')

    async def on_message(self, msg):
        obj = json.loads(msg)
        self.ping()

        JudgeDispatcher.emit_chal(obj, lambda res: self.write_message(json.dumps(res)))

    def on_close(self):
        print(self.close_code, self.close_reason)
        utils.logger.info(f'Backend disconnected close_code: {self.close_code} close_reason: {self.close_reason}')

    def check_origin(self, _: str) -> bool:
        return True

def init_socket_server():
    app = tornado.web.Application([
        (r"/judge", JudgeWebSocketClient),
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
