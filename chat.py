from config import ask

print("Чат с GLM. Для выхода введите: exit / quit / выход")
while True:
    try:
        prompt = input("\nВы: ")
    except (EOFError, KeyboardInterrupt):
        break
    if prompt.strip().lower() in ("exit", "quit", "выход"):
        break
    if not prompt.strip():
        continue
    print("GLM: ", ask(prompt))
