import os


def file_exists(file_name: str) -> bool:
    """checks whether file already exists"""
    # TODO: micropython
    return file_name in os.listdir()
