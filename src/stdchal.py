import threading
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
    PartialCorrect = 2
    WrongAnswer = 3
    RuntimeError = 4 # Re:從零開始的競賽生活
    RuntimeErrorSignalled = 5 # 請不要把OJ當CTF打
    TimeLimitExceeded = 6
    MemoryLimitExceeded = 7
    OutputLimitExceeded = 8
    CompileError = 9 # 再不編譯啊
    CompileLimitExceeded = 10 # 沒事不要炸Judge
    InternalError = 11
    SpecialJudgeError = 12
    """
    Accepted = 1
    PartialCorrect = 2
    WrongAnswer = 3
    RuntimeError = 4 # Re:從零開始的競賽生活
    RuntimeErrorSignalled = 10 # 請不要把OJ當CTF打
    TimeLimitExceeded = 5
    MemoryLimitExceeded = 6
    CompileError = 7 # 再不編譯啊
    OutputLimitExceeded = 9
    CompileLimitExceeded = 11 # 沒事不要炸Judge
    InternalError = 8
    """
    STRMAP = {
        "AC": Accepted,
        "PC": PartialCorrect,
        "WA": WrongAnswer,
        "RE": RuntimeError,
        "RESIG": RuntimeErrorSignalled,
        "TLE": TimeLimitExceeded,
        "MLE": MemoryLimitExceeded,
        "OLE": OutputLimitExceeded,
        "CE": CompileError,
        "CLE": CompileLimitExceeded,
        "IE": InternalError,
        "SJE": SpecialJudgeError,
    }

SignalErrorMessage = {
    4: 'illegal hardware instruction',
    6: 'abort',
    8: 'floating point exception',
    11: 'segmentation fault'
}

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

    def start(self):
        utils.logger.info(f"StdChal {self.chal_id} started")
        if self.comp_typ in ['g++', 'clang++']:
            res, verdict = self.comp_cxx()

        elif self.comp_typ in ['gcc', 'clang']:
            res, verdict = self.comp_c()

        elif self.comp_typ == 'makefile':
            res, verdict = self.comp_make()

        elif self.comp_typ == 'python3':
            res, verdict = self.comp_python()

        elif self.comp_typ == 'rustc':
            res, verdict = self.comp_rustc()

        elif self.comp_typ == 'java':
            t, class_name = self.comp_java()
            res, verdict = t
        else:
            utils.logger.warning(f"StdChal {self.chal_id} uses an unsupported language.")
            return

        checker_fileid = None
        fileid = verdict

        if self.judge_typ in ['ioredir', 'cms']:
            checker_res, checker_fileid = self.comp_checker()
            if checker_res != GoJudgeStatus.Accepted:
                for res in self.results:
                    res['status'] = Status.InternalError

                utils.logger.warning(f"StdChal {self.chal_id} checker compile failed")
                if checker_fileid and executor_server.file_delete(checker_fileid) == 0:
                    utils.logger.warning(f"StdChal {self.chal_id} delete cached checker file {fileid} failed.")

                if executor_server.file_delete(fileid) == 0:
                    utils.logger.warning(f"StdChal {self.chal_id} delete cached file {fileid} failed.")

                return self.results

        utils.logger.info(f"StdChal {self.chal_id} compiled")
        if res != GoJudgeStatus.Accepted:
            return self.results

        if self.comp_typ == "python3":
            args = ["/usr/bin/python3", "a"]
        elif self.comp_typ == "java":
            args = ["/usr/bin/java", f"{class_name}"]
        else:
            args = ["a"]

        if self.comp_typ != 'java':
            for i, test_groups in enumerate(self.test_list):
                t = threading.Thread(target=self.judge_diff_group, args=(i, test_groups, fileid, checker_fileid, args))
                t.start()
                t.join()
        else:
            for i, test_groups in enumerate(self.test_list):
                t = threading.Thread(target=self.judge_diff_group_for_java, args=(i, class_name, test_groups, fileid, args))
                t.start()
                t.join()

        if checker_fileid and executor_server.file_delete(checker_fileid) == 0:
            utils.logger.warning(f"StdChal {self.chal_id} delete cached checker file {fileid} failed.")

        if executor_server.file_delete(fileid) == 0:
            utils.logger.warning(f"StdChal {self.chal_id} delete cached file {fileid} failed.")

        v = '\n'.join(f"Task {idx + 1}: {res['verdict']}" for idx, res in enumerate(self.results) if res['verdict'] != "")

        for res in self.results:
            if res['status'] is None:
                res['status'] = Status.InternalError

            res['verdict'] = v

        utils.logger.info(f"StdChal {self.chal_id} done")
        return self.results

    def judge_diff_group(self, group_index, test_groups, fileid, checker_fileid, run_args):
        if self.judge_typ == 'ioredir' and checker_fileid is not None:
            for tests in test_groups:
                self.judge_diff_ioredir(run_args, group_index, fileid, checker_fileid, tests['in'], tests['ans'], tests['timelimit'], tests['memlimit'])
                if self.results[group_index]['status'] != Status.Accepted:
                    break

        elif self.judge_typ == 'cms' and checker_fileid is not None:
            for tests in test_groups:
                self.judge_diff_cms(run_args, group_index, fileid, checker_fileid, tests['in'], tests['ans'], tests['timelimit'], tests['memlimit'])
                if self.results[group_index]['status'] != Status.Accepted:
                    break
        else:
            for tests in test_groups:
                self.judge_diff(run_args, group_index, fileid, tests['in'], tests['ans'], tests['timelimit'], tests['memlimit'])
                if self.results[group_index]['status'] != Status.Accepted:
                    break

    def judge_diff_group_for_java(self, group_index, class_name, test_groups, fileid, run_args):
        for tests in test_groups:
            self.judge_diff_4_java(run_args, class_name, group_index, fileid, tests['in'], tests['ans'], tests['timelimit'], tests['memlimit'])
            if self.results[group_index]['status'] != Status.Accepted:
                break

    def judge_diff_4_java(self, args, class_name, test_groups, fileid, in_path, ans_path, timelimit, memlimit):
        # java好煩
        result = self.results[test_groups]
        if result["status"] in [Status.TimeLimitExceeded, Status.MemoryLimitExceeded, Status.RuntimeError, Status.RuntimeErrorSignalled, Status.InternalError]:
            return


        res = executor_server.exec({
            "cmd": [{
                "args": [*args],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "src": in_path
                }, {
                    "name": "stdout",
                    "max": 268435456
                }, {
                    "name": "stderr",
                    "max": 10240,
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
        result['time'] = max(res['runTime'], result['time'])
        result['memory'] = max(res['memory'], result['memory'])

        if res['status'] == GoJudgeStatus.Accepted:
            if result['status'] is Status.Accepted or result['status'] is None:
                with open(ans_path, 'r') as ans_file:
                    if self.judge_typ == "diff":
                        res_pass = executor_server.diff_ignore_space(res['files']['stdout'], ans_file.read())
                    elif self.judge_typ == "diff-strict":
                        res_pass = executor_server.diff_strictly(res['files']['stdout'], ans_file.read())

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
                result['verdict'] = res['files']['stderr']

            elif res['status'] == GoJudgeStatus.Signalled:
                result['status'] = Status.RuntimeErrorSignalled

            else:
                result['status'] = Status.InternalError

    def judge_diff(self, args, test_groups, fileid, in_path, ans_path, timelimit, memlimit):
        result = self.results[test_groups]
        if result["status"] in [Status.TimeLimitExceeded, Status.MemoryLimitExceeded, Status.RuntimeError, Status.RuntimeErrorSignalled, Status.InternalError]:
            return

        res = executor_server.exec({
            "cmd": [{
                "args": [*args],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "src": in_path
                }, {
                    "name": "stdout",
                    "max": 268435456
                }, {
                    "name": "stderr",
                    "max": 10240,
                }],
                "cpuLimit": timelimit,
                "memoryLimit": memlimit,
                "stackLimit": 65536 * 1024,
                "procLimit": 1,
                "cpuRateLimit": 1000,
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
        result['time'] = max(res['runTime'], result['time'])
        result['memory'] = max(res['memory'], result['memory'])

        if res['status'] == GoJudgeStatus.Accepted:
            if result['status'] is Status.Accepted or result['status'] is None:
                with open(ans_path, 'r') as ans_file:
                    if self.judge_typ == "diff":
                        res_pass = executor_server.diff_ignore_space(res['files']['stdout'], ans_file.read())
                    elif self.judge_typ == "diff-strict":
                        res_pass = res['files']['stdout'] == ans_file.read()

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
                result['verdict'] = res['files']['stderr']
                result['status'] = Status.RuntimeError

            elif res['status'] == GoJudgeStatus.Signalled:
                result['status'] = Status.RuntimeErrorSignalled
                if res['exitStatus'] in SignalErrorMessage:
                    result['verdict'] = SignalErrorMessage[res['exitStatus']]

            else:
                result['status'] = Status.InternalError

    def judge_diff_cms(self, args, test_groups, fileid, checker_fileid, in_path, ans_path, timelimit, memlimit):
        result = self.results[test_groups]
        if result["status"] in [Status.TimeLimitExceeded, Status.MemoryLimitExceeded, Status.RuntimeError, Status.RuntimeErrorSignalled, Status.InternalError]:
            return

        res = executor_server.exec({
            "cmd": [{
                "args": [*args],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "src": in_path
                }, {
                    "name": "stdout",
                    "max": 268435456
                }, {
                    "name": "stderr",
                    "max": 10240,
                }],
                "cpuLimit": timelimit,
                "memoryLimit": memlimit,
                "stackLimit": 65536 * 1024,
                "procLimit": 1,
                "cpuRateLimit": 1000,
                "strictMemoryLimit": False, # 開了會直接Signalled，會讓使用者沒辦法判斷
                "copyIn": {
                    "a": {
                        "fileId": fileid
                    }
                },
                "copyOutCached": ["stdout"]
            }]
        })
        res = res["results"][0]
        stdout_fileid = res["fileIds"]["stdout"]

        checker_res = executor_server.exec({
            "cmd": [{
                "args": ["check", "test_in", "test_out", "user_ans"],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "content": ""
                }, {
                    "name": "stdout",
                    "max": 10240
                }, {
                    "name": "stderr",
                    "max": 10240,
                }],
                "cpuLimit": timelimit * 2,
                "memoryLimit": memlimit,
                "stackLimit": 65536 * 1024,
                "procLimit": 10,
                "cpuRateLimit": 1000,
                "strictMemoryLimit": False, # 開了會直接Signalled，會讓使用者沒辦法判斷
                "copyIn": {
                    "check": {
                        "fileId": checker_fileid
                    },
                    "test_in": {
                        "src": in_path
                    },
                    "test_ans": {
                        "src": ans_path
                    },
                    "user_ans": {
                        "fileId": stdout_fileid
                    }
                },
                "copyOut": ["stdout", "stderr"]
            }]
        })
        checker_res = checker_res["results"][0]

        result['time'] = max(res['runTime'], result['time'])
        result['memory'] = max(res['memory'], result['memory'])

        if res['status'] == GoJudgeStatus.Accepted:
            if checker_res['status'] == GoJudgeStatus.Accepted:
                result['status'] = Status.Accepted

            elif checker_res['status'] == GoJudgeStatus.NonzeroExitStatus:
                result['status'] = Status.WrongAnswer
                result['verdict'] = checker_res['files']['stderr']

            else:
                result['status'] = Status.SpecialJudgeError


        else:
            if res['status'] == GoJudgeStatus.TimeLimitExceeded:
                result['status'] = Status.TimeLimitExceeded

            elif res['status'] == GoJudgeStatus.MemoryLimitExceeded:
                result['status'] = Status.MemoryLimitExceeded

            elif res['status'] == GoJudgeStatus.OutputLimitExceeded:
                result['status'] = Status.OutputLimitExceeded

            elif res['status'] == GoJudgeStatus.NonzeroExitStatus:
                result['verdict'] = res['files']['stderr']
                result['status'] = Status.RuntimeError

            elif res['status'] == GoJudgeStatus.Signalled:
                result['status'] = Status.RuntimeErrorSignalled

            else:
                result['status'] = Status.InternalError

        if executor_server.file_delete(stdout_fileid) == 0:
            utils.logger.warning(f"StdChal {self.chal_id} delete cached stdout file {stdout_fileid} failed.")


    def judge_diff_ioredir(self, args, test_groups, fileid, checker_fileid, in_path, ans_path, timelimit, memlimit):
        result = self.results[test_groups]
        if result["status"] in [Status.TimeLimitExceeded, Status.MemoryLimitExceeded, Status.RuntimeError, Status.RuntimeErrorSignalled, Status.InternalError]:
            return

        test_files = {
            0: None,
            1: None,
            2: {
                "name": "stderr",
                "max": 10240,
            },
        }
        checker_files = {
            0: None,
            1: {
                "name": "stdout",
                "max": 10240,
            },
            2: {
                "name": "stderr",
                "max": 10240,
            },
        }
        pipe_mappings = []

        test_files[self.metadata["redir_test"]["testin"]] = {
            "src": in_path
        }

        test_files[self.metadata["redir_test"]["testout"]] = None
        test_files[self.metadata["redir_test"]["pipein"]] = None
        test_files[self.metadata["redir_test"]["pipeout"]] = None
        try:
            test_files.pop(-1)
        except KeyError:
            pass

        checker_files[self.metadata["redir_check"]["ansin"]] = {
            "src": ans_path
        }
        checker_files[self.metadata["redir_check"]["testin"]] = {
            "src": in_path
        }
        checker_files[self.metadata["redir_check"]["pipein"]] = None
        checker_files[self.metadata["redir_check"]["pipeout"]] = None
        try:
            checker_files.pop(-1)
        except KeyError:
            pass

        pipe_mappings.append({
            "in": {"index": 0, "fd": self.metadata["redir_test"]["pipeout"]},
            "out": {"index": 1, "fd": self.metadata["redir_check"]["pipeout"]},
            "proxy": True,
        })

        if self.metadata["redir_test"]["pipein"] != -1 and self.metadata["redir_check"]["pipein"] != -1:
            pipe_mappings.append({
                "in": {"index": 1, "fd": self.metadata["redir_check"]["pipein"]},
                "out": {"index": 0, "fd": self.metadata["redir_test"]["pipein"]},
            })

        res = executor_server.exec({
            "cmd": [{
                "args": [*args],
                "env": ["PATH=/usr/bin:/bin"],
                "files": list(test_files.values()),
                "cpuLimit": timelimit,
                "memoryLimit": memlimit,
                "stackLimit": 65536 * 1024,
                "procLimit": 1,
                "cpuRateLimit": 1000,
                "strictMemoryLimit": False, # 開了會直接Signalled，會讓使用者沒辦法判斷
                "copyIn": {
                    "a": {
                        "fileId": fileid
                    }
                },
            },
            {
                "args": ['check'],
                "env": ["PATH=/usr/bin:/bin"],
                "files": list(checker_files.values()),
                "cpuLimit": timelimit, # 5 sec
                "memoryLimit": 536870912, # 512M (256 << 20)
                "procLimit": 10,
                "strictMemoryLimit": False, # 開了會直接Signalled，會讓使用者沒辦法判斷
                "copyIn": {
                    "check": {
                        "fileId": checker_fileid
                    }
                },
            }],
            "pipeMapping": pipe_mappings,
        })
        checker_res = res["results"][1]
        res = res["results"][0]
        result['time'] = max(res['runTime'], result['time'])
        result['memory'] = max(res['memory'], result['memory'])

        # SIGPIPE -> checker failed
        if res['status'] == GoJudgeStatus.Signalled and res['exitStatus'] == 13: # SIGPIPE
            result['status'] = Status.SpecialJudgeError
            return

        if res['status'] == GoJudgeStatus.Accepted:
            if checker_res['status'] == GoJudgeStatus.Accepted:
                result['status'] = Status.Accepted
            elif checker_res['status'] == GoJudgeStatus.NonzeroExitStatus:
                result['status'] = Status.WrongAnswer
            else:
                result['status'] = Status.SpecialJudgeError
                # checker failed

        else:
            if res['status'] == GoJudgeStatus.TimeLimitExceeded:
                result['status'] = Status.TimeLimitExceeded

            elif res['status'] == GoJudgeStatus.MemoryLimitExceeded:
                result['status'] = Status.MemoryLimitExceeded

            elif res['status'] == GoJudgeStatus.OutputLimitExceeded:
                result['status'] = Status.OutputLimitExceeded

            elif res['status'] == GoJudgeStatus.NonzeroExitStatus:
                result['verdict'] = res['files']['stderr']
                result['status'] = Status.RuntimeError

            elif res['status'] == GoJudgeStatus.Signalled:
                result['status'] = Status.RuntimeErrorSignalled

            else:
                result['status'] = Status.InternalError

    def comp_checker(self):
        res_checker_path = f"{self.res_path}/check"
        copy_in: dict[str, dict[str, str]] = {}
        for file in os.listdir(res_checker_path):
            if os.path.isfile(os.path.join(res_checker_path, file)):
                copy_in[file] = {
                    "src": os.path.join(res_checker_path, file)
                }

        res = executor_server.exec({
            "cmd": [{
                "args": ["/usr/bin/sh", "build"],
                "env": ["PATH=/usr/bin:/bin"],
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
                    **copy_in
                },
                "copyOut": ["stderr"],
                "copyOutCached": ["check"]
            }]
        })
        res = res["results"][0]
        return self.compile_update_result(res, "check")

    def comp_cxx(self):
        if self.comp_typ == 'g++':
            compiler = '/usr/bin/g++'
            standard = '-std=gnu++17'
            options = ['-O2']
        else:
            compiler = '/usr/bin/clang++'
            standard = '-std=c++17'
            options = ['-O2']

        res = executor_server.exec({
            "cmd": [{
                "args": [compiler, standard, *options, "-pipe", "-static", "a.cpp", "-o", "a"],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "content": ""
                }, {
                    "content": ""
                }, {
                    "name": "stderr",
                    "max": 102400
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
                "copyOutCached": ["a"],
                "copyOutMax": 64000000
            }]
        })
        res = res["results"][0]
        return self.compile_update_result(res, "a")

    def comp_c(self):
        if self.comp_typ == 'gcc':
            compiler = '/usr/bin/gcc'
            standard = "-std=gnu11"
        else:
            compiler = '/usr/bin/clang'
            standard = '-std=c11'

        res = executor_server.exec({
            "cmd": [{
                "args": [compiler, standard, "-O2", "-pipe", "-static", "a.c", "-o", "a", "-lm"],
                "env": ["PATH=/usr/bin:/bin"],
                "files": [{
                    "content": ""
                }, {
                    "content": ""
                }, {
                    "name": "stderr",
                    "max": 102400
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
                "copyOutCached": ["a"],
                "copyOutMax": 64000000
            }]
        })
        res = res["results"][0]
        return self.compile_update_result(res, "a")

    def comp_rustc(self):
        res = executor_server.exec({
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
                "copyOutCached": ["a"],
                "copyOutMax": 64000000
            }]
        })
        res = res["results"][0]
        return self.compile_update_result(res, "a")

    def comp_python(self):
        res = executor_server.exec({
            "cmd": [{
                "args": ["/usr/bin/python3", "-c", '''import py_compile; py_compile.compile('a.py', 'a.pyc', doraise=True, optimize=2)'''],
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
                "copyOutCached": ["a.pyc"],
                "copyOutMax": 64000000
            }]
        })
        res = res["results"][0]
        return self.compile_update_result(res, "a.pyc")

    def comp_java(self):
        with open(self.code_path, 'r') as java_file:
            main_class_name = utils.get_java_main_class(java_file.read())
            if main_class_name == "":
                for result in self.results:
                    result["verdict"] = "Your main class not found or invalid class name or more than one main function."
                    result["status"] = Status.CompileError

                return (GoJudgeStatus.NonzeroExitStatus, None), ""

        res = executor_server.exec({
            "cmd": [{
                "args": ["/usr/bin/javac", f"{main_class_name}.java"],
                "env": ["PATH=/usr/bin:/bin", "JAVA_HOME=/lib/jvm/java-17-openjdk-amd64"],
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
                "copyOutCached": [f"{main_class_name}.class"],
                "copyOutMax": 64000000
            }]
        })
        res = res["results"][0]

        # Java Output maybe in stdout or stderr
        if res["files"]["stderr"] == "" and res["files"]["stdout"] != "":
            res["files"]["stderr"] = res["files"]["stdout"]

        return (self.compile_update_result(res, f"{main_class_name}.class"), main_class_name)

    def comp_make(self):
        # 23 38 59 75 76 81 85 164 187 233 239 300 302 545 659

        res_make_path = f"{self.res_path}/make"
        copy_in: dict[str, dict[str, str]] = {}
        for file in os.listdir(res_make_path):
            if os.path.isfile(os.path.join(res_make_path, file)):
                copy_in[file] = {
                    "src": os.path.join(res_make_path, file)
                }

        res = executor_server.exec({
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
                "copyOutCached": ["a"],
                "copyOutMax": 64000000
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
