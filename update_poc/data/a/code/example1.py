import sys


def example() -> None:
    print("Hello World!")


def main() -> int:
    example()
    return 1


if __name__ == "__main__":
    sys.exit(main())
