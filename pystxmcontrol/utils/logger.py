import logging, sys, time, functools


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
