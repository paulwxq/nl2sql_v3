#!/usr/bin/env python3
import os
for f in os.listdir('docs'):
    if '70' in f and f.endswith('.md'):
        filepath = os.path.join('docs', f)
        print(f"File: {filepath}")
        with open(filepath, encoding='utf-8') as file:
            for i, line in enumerate(file, 1):
                if 'namespace =' in line or 'WHERE namespace' in line or 'namespace =' in line.lower():
                    print(f"  {i}: {line.strip()[:100]}")

