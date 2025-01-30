import logging


def getLogger(name) -> logging.Logger:
    return logging.getLogger("sbomify." + name)
