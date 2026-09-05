import gradio as gr

from config import ask


def chat(message, history):
    return ask(message, history)


gr.ChatInterface(
    chat,
    title="Чат с GLM",
    examples=["Привет! Расскажи о себе"],
).launch(server_name="0.0.0.0")
