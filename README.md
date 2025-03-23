# InnVision

InnVision is an automated platform based on artificial intelligence for generating and translating textual content. The platform is built on a microservice architecture and includes several specialized services for efficient text management, automatic order search, customer interaction, content generation, and text quality control.

## Principal Components.

- Aggregator Service: Сервис, который агрегирует заказы с различных платформ (например, Fiverr, Upwork), проводит первичный анализ и маршрутизацию запросов.
- Orchestrator Service: Координирует выполнение задач, направляет запросы между сервисами и обеспечивает бесперебойную работу системы.
- Role General Service: Отвечает за генерацию текстов в различных стилях (копирайтинг, маркетинговые тексты, рекламные материалы).
- QA Service: Проверяет созданный контент на соответствие стандартам качества, грамматическим и стилистическим требованиям, а также на отсутствие запрещенных слов.
- Translation Service: Автоматизирует перевод текстов, поддерживая интеграцию с популярными сервисами перевода (Google, DeepL, GPT).

## Technology Stack.

- Python 3.11
- FastAPI
- PostgreSQL
- GPT (OpenAI API)
- Docker & Docker Compose
- ChromaDB for vector data storage

## Project Maintainers

<table>
  <tr>
    <td align="center"><a href="https://github.com/AngryX-27"><img src="https://avatars.githubusercontent.com/u/200900751?u=78819056ffb29fc0304de5f7e949203616343b8e&v=4" width="100px;" alt=""/><br /><sub><b>Grigoriy AngryX</b></sub></a></td>
  </tr>
</table>


---


# InnVision

InnVision — это автоматизированная платформа на основе искусственного интеллекта, предназначенная для генерации и перевода текстового контента. Платформа построена на микросервисной архитектуре и включает несколько специализированных сервисов для эффективного управления текстами, автоматического поиска заказов, взаимодействия с клиентами, генерации контента, а также обеспечения контроля качества текстов.

## Основные компоненты.

- Aggregator Service: Сервис, который агрегирует заказы с различных платформ (например, Fiverr, Upwork), проводит первичный анализ и маршрутизацию запросов.
- Orchestrator Service: Координирует выполнение задач, направляет запросы между сервисами и обеспечивает бесперебойную работу системы.
- Role General Service: Отвечает за генерацию текстов в различных стилях (копирайтинг, маркетинговые тексты, рекламные материалы).
- QA Service: Проверяет созданный контент на соответствие стандартам качества, грамматическим и стилистическим требованиям, а также на отсутствие запрещенных слов.
- Translation Service: Автоматизирует перевод текстов, поддерживая интеграцию с популярными сервисами перевода (Google, DeepL, GPT).

## Технологический стек.

- Python 3.11
- FastAPI
- PostgreSQL
- GPT (OpenAI API)
- Docker и Docker Compose
- ChromaDB для хранения векторных данных

## Руководители проекта

<table>
  <tr>
    <td align="center"><a href="https://github.com/AngryX-27"><img src="https://avatars.githubusercontent.com/u/200900751?u=78819056ffb29fc0304de5f7e949203616343b8e&v=4" width="100px;" alt=""/><br /><sub><b>Григорий AngryX</b></sub></a></td>
  </tr>
</table>
