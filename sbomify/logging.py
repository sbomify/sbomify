import logging


def getLogger(name: str) -> logging.Logger:
    return logging.getLogger("sbomify." + name)
