#!/usr/bin/env python3
import os
import sys

start = int(sys.argv[1]) if len(sys.argv) > 1 else 1405
end = int(sys.argv[2]) if len(sys.argv) > 2 else 1425

for f in os.listdir('docs'):
    if '70' in f and f.endswith('.md'):
        filepath = os.path.join('docs', f)
        with open(filepath, encoding='utf-8') as file:
            lines = file.readlines()
            for i in range(start-1, min(end, len(lines))):
                print(f'{i+1}: {lines[i].rstrip()}')

