import re
import logging

import config

logger = logging.getLogger("Judge")
logger.setLevel(config.LOGGER_LEVEL)
handler = logging.StreamHandler()
if config.LOGGER_LEVEL == logging.DEBUG:
    formatter = logging.Formatter('%(asctime)s %(filename)s %(name)s - %(levelname)s: %(message)s')
else:
    formatter = logging.Formatter('%(asctime)s %(name)s %(message)s')

handler.setFormatter(formatter)
logger.addHandler(handler)

IS_CLASS_NAME_VALID_PATTERN = re.compile(r"(^\d)|[`~!@#%^&*()+={}|'\"?\/<>,.:;\[\]{}\\]")
MAIN_FUNC_PATTERN = re.compile(r"\n\s*public static void main")

def get_java_main_class(source: str) -> str:
    main_class_name = ""
    cnt = 0
    for i in re.split('class ', source):                 # will match the main code block and the class name of all classes
        if MAIN_FUNC_PATTERN.search(i):              # check if 'public static void main' in a class
            main_class_name = re.search('(\w*)', i).group(1)
            if not IS_CLASS_NAME_VALID_PATTERN.match(main_class_name):
                cnt += 1

    if cnt == 1:
        return main_class_name

    return ""
