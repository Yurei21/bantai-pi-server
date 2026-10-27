#!/bin/bash
export PATH=/home/bantai/.local/bin:$PATH
export PYTHONPATH=/home/bantai/bantai-server:$PYTHONPATH
cd /home/bantai/bantai-server
python3 app.py
