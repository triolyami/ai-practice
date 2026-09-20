# Android-клиент: Kotlin + MVI

## Стек
- язык: только Kotlin; Java-код и другие языки не предлагать
- ui: Jetpack Compose; XML-вёрстка и View-система запрещены
- архитектура: MVI — однонаправленный поток, единый state на экран
- асинхронность: корутины и Flow; RxJava запрещена
- di: ручная сборка зависимостей; Dagger/Hilt запрещены

## Стиль
- ответы: код на Kotlin, пояснения кратко и по делу

## Проверки
- бан-код: (?i)rxjava|io\.reactivex
- бан-код: (?i)dagger|hilt|javax\.inject|@inject|@module|@component
- бан: (?i)react native|flutter
