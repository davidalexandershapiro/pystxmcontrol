import logging, sys, time, functools

LOG_FORMAT = '%(levelname)s:%(name)s:%(funcName)s:%(lineno)d: %(message)s'


class ColorFormatter(logging.Formatter):
    _COLORS = {
        logging.DEBUG:    '\033[36m',
        logging.INFO:     '\033[32m',
        logging.WARNING:  '\033[33m',
        logging.ERROR:    '\033[31m',
        logging.CRITICAL: '\033[1;31m',
    }
    _RESET = '\033[0m'

    def format(self, record):
        color = self._COLORS.get(record.levelno, '')
        record.levelname = f"{color}{record.levelname}{self._RESET}"
        return super().format(record)


import os as _os
_LOG_LEVEL = getattr(logging, _os.environ.get("PYSTXM_LOG_LEVEL", "INFO").upper(), logging.INFO)


def get_logger(name):
    """Return a module-level logger with color formatting.

    Log level is controlled by the PYSTXM_LOG_LEVEL env var (default INFO).
    e.g. export PYSTXM_LOG_LEVEL=DEBUG
    """
    log = logging.getLogger(name)
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(ColorFormatter(LOG_FORMAT))
        log.addHandler(handler)
    log.setLevel(_LOG_LEVEL)
    return log


# TODO: should this class be replaced with a stdlib logger + FileHandler?
# It only adds file output and a decorator pattern over the stdlib logger,
# but is missing warning/error/critical levels. A FileHandler on get_logger()
# would cover the file-logging use case and unify the two logging systems.
class logger(object):
    def __init__(self, name = None, outfile = None):
        super(logger, self).__init__()

        if name is None:
            self._name = 'ROOT'
        else: 
            self._name = name
        if outfile is None:
            self._outfile = '/dev/pts/0'
        else:
            self._outfile = outfile

        logging.basicConfig(filename = self._outfile, filemode='a', \
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',\
                datefmt = '%d-%b-%y %H:%M:%S', level = logging.DEBUG)
        self.logger = logging.getLogger(self._name)

    def log(self, message = None, level = 'debug'):
        if level == 'info':
            self.logger.info(message)
        elif level == 'debug':
            self.logger.debug(message)

    def __call__(self, fn):
        @functools.wraps(fn)
        def decorated(*args, **kwargs):
            try:
                #self.logger.debug("{0} - {1} - {2}".format(fn.__name__, args, kwargs))
                result = fn(*args, **kwargs)
                #self.logger.debug(result)
                self.log(result)
                return result
            except Exception as ex:
                self.logger.debug("Exception {0}".format(ex))
                raise ex
            return result
        return decorated
