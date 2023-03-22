import tkinter as tk
from tkinter import messagebox
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import argparse
import logging

def main(loglevel):         

    # Start web server in the cesium_app directory (which contains the `index.html` file which then references the eosimApp.js script).
    httpd = HTTPServer(('localhost', 5001), SimpleHTTPRequestHandler)
    def start_webserver():
        web_dir = os.path.join(os.path.dirname(__file__), '../cesium_app/')
        os.chdir(web_dir)      
        print("server starting")
        httpd.serve_forever()
    threading.Thread(target=start_webserver).start() # creating a thread so that the GUI doesn't freeze.


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Earth Observation Simulator (EOSim)'
    )
    parser.add_argument(
        '-loglevel',
        default="INFO",
        type=str,
        help="Logging level: Specify CRITICAL or ERROR or WARNING or INFO or DEBUG."
    )   

    args = parser.parse_args()
    if(args.loglevel=='CRITICAL'):
        loglevel = logging.CRITICAL
    elif(args.loglevel=='ERROR'):
        loglevel = logging.ERROR
    elif(args.loglevel=='WARNING'):
        loglevel = logging.WARNING
    elif(args.loglevel=='INFO'):
        loglevel = logging.INFO
    elif(args.loglevel=='DEBUG'):
        loglevel = logging.DEBUG

    main(loglevel)