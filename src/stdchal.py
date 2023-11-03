import asyncio
import os
from typing import Dict, List

import executor_server
import utils


class GoJudgeStatus:
    Accepted = 'Accepted'
    MemoryLimitExceeded = 'Memory Limit Exceeded'
    TimeLimitExceeded = 'Time Limit Exceeded'
    OutputLimitExceeded = 'Output Limit Exceeded'
    FileError = 'File Error'
    NonzeroExitStatus = 'Nonzero Exit Status'
    Signalled = 'Signalled'
    InternalError = 'Internal Error'

class Status:
    Accepted = 1
    WrongAnswer = 2
    RuntimeError = 3 # Re:從零開始的競賽生活
    TimeLimitExceeded = 4
    MemoryLimitExceeded = 5
    CompileError = 6 # 再不編譯啊
    InternalError = 7
    OutputLimitExceeded = 8
    RuntimeErrorSignalled = 9 # 請不要把OJ當CTF打
    CompileLimitExceeded = 10 # 沒事不要炸Judge

class StdChal:
    def __init__(self, chal_id: int, code_path: str, comp_typ: str, judge_typ: str, res_path: str, test_list: List, metadata: Dict) -> None:
        self.code_path = code_path
        self.res_path = res_path
        self.comp_typ = comp_typ
        self.judge_typ = judge_typ
        self.test_list = test_list
        self.metadata = metadata
        self.chal_id = chal_id
        self.chal_path = None

        self.results = []
        for _ in range(len(test_list)):
            self.results.append({
                "status": None,
                "time": 0,
                "memory": 0,
                "verdict": "",
            })

    async def start(self):
        utils.logger.info(f"StdChal {self.chal_id} started")
        if self.comp_typ in ['g++', 'clang++']:
            res, verdict = await self.comp_cxx()

        elif self.comp_typ in ['gcc', 'clang']:
            res, verdict = await self.comp_c()

        elif self.comp_typ == 'makefile':
            res, verdict = await self.comp_make()

        elif self.comp_typ == 'python3':
            res, verdict = await self.comp_python()

        elif self.comp_typ == 'rustc':
            res, verdict = await self.comp_rustc()

        elif self.comp_typ == 'java':
            t, class_name = await self.comp_java()
            res, verdict = t

        utils.logger.info(f"StdChal {self.chal_id} compiled")
        if res != GoJudgeStatus.Accepted:
            return self.results

        if self.comp_typ == "python3":
            args = ["/usr/bin/python3.11", "a"]
        elif self.comp_typ == "java":
            args = ["/usr/bin/java", f"{class_name}"]
        else:
            args = ["a"]

        fileid = verdict
        tasks = []
        if self.comp_typ != 'java':
            for i, test_groups in enumerate(self.test_list):
                for tests in test_groups:
                    tasks.append(self.judge_diff(args, i, fileid, tests['in'], tests['ans'], tests['timelimit'], tests['memlimit']))
        else:
            for i, test_groups in enumerate(self.test_list):
                for tests in test_groups:
                    tasks.append(self.judge_diff_4_java(args, class_name,
                                                        i, fileid, tests['in'], tests['ans'], tests['timelimit'], tests['memlimit']))

        await asyncio.gather(*tasks)
        await executor_server.file_delete(fileid)

        utils.logger.info(f"StdChal {self.chal_id} done")
        return self.results

    async def judge_diff_4_java(self, args, class_name, test_groups, fileid, in_path, ans_path, timelimit, memlimit):
        # java好煩
        result = self.results[test_groups]
        if result["status"] in [Status.TimeLimitExceeded, Status.MemoryLimitExceeded, Status.RuntimeError, Status.RuntimeErrorSignalled]:
            return

        res = await executor_server.exec({
            "cmd": [{
                "args": [*args],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "src": in_path
                }, {
                    "name": "stdout",
                    "max": 102400
                }, {
                    "content": ""
                }],
                "cpuLimit": timelimit,
                "memoryLimit": memlimit,
                "procLimit": 25, # java可能要大一點
                "strictMemoryLimit": False, # 開了會直接Signalled，會讓使用者沒辦法判斷
                "copyIn": {
                    f"{class_name}.class": {
                        "fileId": fileid
                    }
                },
                "copyOut": ["stdout"]
            }]
        })
        res = res["results"][0]
        result['time'] += res['runTime']
        result['memory'] += res['memory']

        if res['status'] == GoJudgeStatus.Accepted:
            with open(ans_path, 'r') as ans_file:
                res_pass = await executor_server.diff_ignore_space(res['files']['stdout'], ans_file.read())
                if res_pass:
                    result['status'] = Status.Accepted
                else:
                    result['status'] = Status.WrongAnswer
        else:
            if res['status'] == GoJudgeStatus.TimeLimitExceeded:
                result['status'] = Status.TimeLimitExceeded

            elif res['status'] == GoJudgeStatus.MemoryLimitExceeded:
                result['status'] = Status.MemoryLimitExceeded

            elif res['status'] == GoJudgeStatus.OutputLimitExceeded:
                result['status'] = Status.OutputLimitExceeded

            elif res['status'] == GoJudgeStatus.NonzeroExitStatus:
                result['status'] = Status.RuntimeError

            elif res['status'] == GoJudgeStatus.Signalled:
                result['status'] = Status.RuntimeErrorSignalled

            else:
                result['status'] = Status.InternalError

    async def judge_diff(self, args, test_groups, fileid, in_path, ans_path, timelimit, memlimit):
        result = self.results[test_groups]
        if result["status"] in [Status.TimeLimitExceeded, Status.MemoryLimitExceeded, Status.RuntimeError, Status.RuntimeErrorSignalled]:
            return

        res = await executor_server.exec({
            "cmd": [{
                "args": [*args],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "src": in_path
                }, {
                    "name": "stdout",
                    "max": 102400
                }, {
                    "content": ""
                }],
                "cpuLimit": timelimit,
                "memoryLimit": memlimit,
                "procLimit": 1,
                "strictMemoryLimit": False, # 開了會直接Signalled，會讓使用者沒辦法判斷
                "copyIn": {
                    "a": {
                        "fileId": fileid
                    }
                },
                "copyOut": ["stdout"]
            }]
        })
        res = res["results"][0]
        result['time'] += res['runTime']
        result['memory'] += res['memory']

        if res['status'] == GoJudgeStatus.Accepted:
            with open(ans_path, 'r') as ans_file:
                res_pass = await executor_server.diff_ignore_space(res['files']['stdout'], ans_file.read())
                if res_pass:
                    result['status'] = Status.Accepted
                else:
                    result['status'] = Status.WrongAnswer
        else:
            if res['status'] == GoJudgeStatus.TimeLimitExceeded:
                result['status'] = Status.TimeLimitExceeded

            elif res['status'] == GoJudgeStatus.MemoryLimitExceeded:
                result['status'] = Status.MemoryLimitExceeded

            elif res['status'] == GoJudgeStatus.OutputLimitExceeded:
                result['status'] = Status.OutputLimitExceeded

            elif res['status'] == GoJudgeStatus.NonzeroExitStatus:
                result['status'] = Status.RuntimeError

            elif res['status'] == GoJudgeStatus.Signalled:
                result['status'] = Status.RuntimeErrorSignalled

            else:
                result['status'] = Status.InternalError

    async def comp_cxx(self):
        if self.comp_typ == 'g++':
            compiler = '/usr/bin/g++'
            standard = '-std=gnu++17'
        else:
            compiler = '/usr/bin/clang++-15'
            standard = '-std=c++17'

        res = await executor_server.exec({
            "cmd": [{
                "args": [compiler, standard, "-O2", "a.cpp", "-o", "a"],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "content": ""
                }, {
                    "content": ""
                }, {
                    "name": "stderr",
                    "max": 10240
                }],
                "cpuLimit": 10000000000, # 10 sec
                "memoryLimit": 536870912, # 512M (256 << 20)
                "procLimit": 10,
                "copyIn": {
                    "a.cpp": {
                        "src": self.code_path
                    }
                },
                "copyOut": ["stderr"],
                "copyOutCached": ["a"]
            }]
        })
        res = res["results"][0]
        return self.compile_update_result(res, "a")

    async def comp_c(self):
        if self.comp_typ == 'gcc':
            compiler = '/usr/bin/gcc'
            standard = "-std=gnu11"
        else:
            compiler = '/usr/bin/clang-15'
            standard = '-std=c11'

        # elif self.comp_typ == 'clang':
        #     compiler = '/usr/bin/clang'
        # else:
        #     compiler = '/usr/bin/tobiichi-c-compiler'

        res = await executor_server.exec({
            "cmd": [{
                "args": [compiler, standard, "-O2", "a.c", "-o", "a", "-lm"],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "content": ""
                }, {
                    "content": ""
                }, {
                    "name": "stderr",
                    "max": 10240
                }],
                "cpuLimit": 10000000000,
                "memoryLimit": 536870912,
                "procLimit": 10,
                "copyIn": {
                    "a.c": {
                        "src": self.code_path
                    }
                },
                "copyOut": ["stderr"],
                "copyOutCached": ["a"]
            }]
        })
        res = res["results"][0]
        return self.compile_update_result(res, "a")

    async def comp_rustc(self):
        res = await executor_server.exec({
            "cmd": [{
                "args": ["/usr/bin/rustc", "./a.rs", "-O", "-o", "a"],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "content": ""
                }, {
                    "content": ""
                }, {
                    "name": "stderr",
                    "max": 10240
                }],
                "cpuLimit": 10000000000,
                "memoryLimit": 1073741824,
                "procLimit": 10,
                "copyIn": {
                    "a.rs": {
                        "src": self.code_path
                    }
                },
                "copyOut": ["stderr"],
                "copyOutCached": ["a"]
            }]
        })
        res = res["results"][0]
        return self.compile_update_result(res, "a")

    async def comp_python(self):
        res = await executor_server.exec({
            "cmd": [{
                "args": ["/usr/bin/python3.11", "-m", "py_compile", "./a.py"],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "content": ""
                }, {
                    "content": ""
                }, {
                    "name": "stderr",
                    "max": 10240
                }],
                "cpuLimit": 10000000000,
                "memoryLimit": 536870912,
                "procLimit": 10,
                "copyIn": {
                    "a.py": {
                        "src": self.code_path
                    }
                },
                "copyOut": ["stderr"],
                "copyOutCached": ["__pycache__/a.cpython-311.pyc"]
            }]
        })
        res = res["results"][0]
        return self.compile_update_result(res, "__pycache__/a.cpython-311.pyc")

    async def comp_java(self):
        with open(self.code_path, 'r') as java_file:
            main_class_name = utils.get_java_main_class(java_file.read())
            if main_class_name == "":
                for result in self.results:
                    result["verdict"] = "Your main class not found or invalid class name or more than one main function."
                    result["status"] = Status.CompileError

                return GoJudgeStatus.NonzeroExitStatus, None

        res = await executor_server.exec({
            "cmd": [{
                "args": ["/usr/bin/javac", f"{main_class_name}.java"],
                "env": ["PATH=/usr/bin:/bin", "JAVA_HOME=/lib/jvm/default-java"],
                "files": [{
                    "content": ""
                }, {
                    "name": "stdout",
                    "max": 10240
                }, {
                    "name": "stderr",
                    "max": 10240
                }],
                "cpuLimit": 10000000000,
                "memoryLimit": 2147483647, # 1024M (1024 << 20)
                "procLimit": 25,
                "copyIn": {
                    f"{main_class_name}.java": {
                        "src": self.code_path
                    }
                },
                "copyOut": ["stdout"],
                "copyOutCached": [f"{main_class_name}.class"]
            }]
        })
        res = res["results"][0]

        # Java Output maybe in stdout or stderr
        if res["files"]["stderr"] == "" and res["files"]["stdout"] != "":
            res["files"]["stderr"] = res["files"]["stdout"]

        return (self.compile_update_result(res, f"{main_class_name}.class"), main_class_name)

    async def comp_make(self):
        # 23 38 59 75 76 81 85 164 187 233 239 300 302 545 659

        res_make_path = f"{self.res_path}/make"
        copy_in: dict[str, dict[str, str]] = {}
        for file in os.listdir(res_make_path):
            if os.path.isfile(os.path.join(res_make_path, file)):
                copy_in[file] = {
                    "src": os.path.join(res_make_path, file)
                }

        res = await executor_server.exec({
            "cmd": [{
                "args": ["/usr/bin/make"],
                "env": ["PATH=/usr/bin:/bin", "OUT=./a"],
                "files": [{
                    "content": ""
                }, {
                    "name": "stdout",
                    "max": 10240
                }, {
                    "name": "stderr",
                    "max": 10240
                }],
                "cpuLimit": 10000000000,
                "memoryLimit": 2147483647,
                "procLimit": 10,
                "copyIn": {
                    "main.cpp": {
                        "src": self.code_path
                    },
                    **copy_in
                },
                "copyOut": ["stderr"],
                "copyOutCached": ["a"]
            }]
        })
        res = res["results"][0]
        return self.compile_update_result(res, "a")

    def compile_update_result(self, res, copy_out_name):
        if res["status"] == GoJudgeStatus.Accepted:
            return res["status"], res["fileIds"][copy_out_name]

        elif res["status"] == GoJudgeStatus.NonzeroExitStatus:
            for result in self.results:
                result["verdict"] = res["files"]["stderr"]
                result["time"] = res["runTime"]
                result["memory"] = res["memory"]
                result["status"] = Status.CompileError

            return res["status"], None

        elif res["status"] in [GoJudgeStatus.TimeLimitExceeded, GoJudgeStatus.MemoryLimitExceeded]:
            for result in self.results:
                result["verdict"] = res["files"]["stderr"]
                result["time"] = res["runTime"]
                result["memory"] = res["memory"]
                result["status"] = Status.CompileLimitExceeded

            return res["status"], None

        else:
            for result in self.results:
                result["status"] = Status.InternalError

            return res["status"], None
