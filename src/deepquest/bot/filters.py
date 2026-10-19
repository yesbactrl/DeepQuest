from aiogram import F

# Свободный текст, но не команда: /cancel и прочие должны доходить до своих обработчиков.
TEXT_ANSWER = F.text & ~F.text.startswith("/")
