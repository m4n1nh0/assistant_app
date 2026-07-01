FROM ollama/ollama:latest

RUN ollama serve & \
    until ollama list > /dev/null 2>&1; do sleep 1; done && \
    ollama pull llama3.2:3b

EXPOSE 11434
CMD ["serve"]
