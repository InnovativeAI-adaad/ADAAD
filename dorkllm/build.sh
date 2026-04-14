#!/bin/bash
# DORK LLM Build Utility
# Creates the 'dork' model in Ollama using the local Modelfile.

echo "[*] Building dork LLM from Modelfile..."

if ! command -v ollama &> /dev/null; then
    echo "[-] Error: ollama is not installed."
    exit 1
fi

ollama create dork -f Modelfile

if [ $? -eq 0 ]; then
    echo "[+] dork model created successfully."
    echo "[*] Use it via: ollama run dork"
else
    echo "[-] Failed to create dork model."
    exit 1
fi
