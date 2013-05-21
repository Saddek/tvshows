# -*- coding: utf-8 -*-
from tvshows import app
import sys

host = '0.0.0.0'
port = 5000

if len(sys.argv) == 2:
    port = int(sys.argv[1])
elif len(sys.argv) >= 3:
    host = sys.argv[1]
    port = int(sys.argv[2])

app.run(host=host, port=port)
