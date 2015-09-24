#!/usr/bin/env python
import hashlib

import time

import click
import sys


@click.command()
@click.option("-s", "--settle-duration", default=5.0, show_default=True,
              help="Duration without change after which file is considered settled.")
@click.option("-t", "--timeout", default=60, show_default=True,
              help="Total timeout after which to abort waiting for file to settle")
@click.argument("filename", type=click.Path(exists=True, dir_okay=False))
def main(settle_duration, timeout, filename):
    window = start = time.time()
    last_sum = ""
    while time.time() - window < settle_duration:
        with open(filename) as file_:
            file_sum = hashlib.sha1(file_.read()).hexdigest()
        if file_sum != last_sum:
            window = time.time()
            last_sum = file_sum
        time.sleep(.2)

        if time.time() - start > timeout:
            print("File '{}' hasn't settled after {} s. Aborting.".format(filename, timeout))
            sys.exit(1)


if __name__ == "__main__":
    main()
