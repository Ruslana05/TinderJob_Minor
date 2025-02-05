import aiosqlite
import logging
import asyncio
import json
import os
import urllib3
from aiogram.filters.state import StateFilter
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, KeyboardButton, ReplyKeyboardMarkup
from aiogram.types import KeyboardButtonPollType, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import BotCommand, BotCommandScopeDefault
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta
from typing import Callable, Any, Awaitable
from urllib3.exceptions import InsecureRequestWarning
# Отключаем предупреждения
urllib3.disable_warnings(InsecureRequestWarning)

# Логирование
logging.basicConfig(force=True, level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.basicConfig()

# Токен бота и инициализация
token = '7641096416:AAH1DOQmRe0lJdlW3NK-eGXqp4LRlKslHyI'
bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# Словарь для хранения задач (чтобы их можно было завершить при необходимости)
active_tasks = {}

# Определение состояний формы
class Form(StatesGroup):
    name = State() # Состояние для ввода ФИО
    telephone = State() # Состояние для ввода номера возраста

async def create_db():
    """Создание таблицы в базе данных для пользователей, если она еще не существует."""
    async with aiosqlite.connect("users.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                last_name TEXT,
                first_name TEXT,
                telephone_number TEXT
            )
        """)
        await db.commit()

async def add_user_to_db(user_id, last_name, first_name, telephone_number):
    """Добавление или обновление пользователя в базе данных."""
    async with aiosqlite.connect("users.db") as db:
        # Проверка на существование пользователя по user_id
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
        if user:
            print(f"User {user_id} already exists. Updating info.")
            await db.execute("UPDATE users SET last_name = ?, first_name = ?, telephone_number = ? WHERE user_id = ?",
                             (last_name, first_name, telephone_number, user_id))
        else:
            print(f"Adding new user {user_id} to the database.")
            await db.execute("INSERT INTO users (user_id, last_name, first_name, telephone_number) VALUES (?, ?, ?, ?)",
                             (user_id, last_name, first_name, telephone_number))
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect("users.db") as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
            if user:
                print(f"User {user_id} found: {user}")
            else:
                print(f"User {user_id} not found.")
            return user

# Middleware для проверки зарегистрированности пользователя
class RegistrationMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[Any], Awaitable[Any]], event: Message | CallbackQuery, data: dict):
        user_id = event.from_user.id

        # Пропускаем команду /start без проверки регистрации
        if isinstance(event, Message) and event.text == "/start":
            return await handler(event, data)

        # Проверка состояния пользователя
        fsm_context = data.get('state', None)
        if fsm_context:
            state = await fsm_context.get_state()
            if state in [Form.name.state, Form.telephone.state]:
                # Если пользователь в процессе регистрации, пропускаем Middleware
                return await handler(event, data)

        # Проверка регистрации пользователя в базе данных
        async with aiosqlite.connect("users.db") as db:
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                user = await cursor.fetchone()

        if not user:  # Если пользователь не найден в базе данных
            if isinstance(event, Message):
                await event.answer("Вы не зарегистрированы! Пожалуйста, начните с команды /start для регистрации.")
            elif isinstance(event, CallbackQuery):
                await event.message.answer("Вы не зарегистрированы! Пожалуйста, начните с команды /start для регистрации.")
            return  # Прерываем обработку события
        return await handler(event, data)

# Регистрируем Middleware в диспетчере
dp.message.middleware(RegistrationMiddleware())
dp.callback_query.middleware(RegistrationMiddleware())

def check_name(name: str):
    return len(name.split()) == 3

def check_telephone(telephone: str):
    return telephone.isdigit()

@dp.message(F.text, Form.name)
async def inputfio(message: Message, state: FSMContext):
    if not check_name(message.text):
        await message.answer(f'ФИО введено некорректно. Повторите ввод')
        return
    await message.answer(f'ФИО принято! Теперь введите ваш номер телефона цифрами:')
    await state.update_data(name=message.text)
    await state.set_state(Form.telephone)

@dp.message(F.text, Form.telephone)
async def input_telephone(message: Message, state: FSMContext):
    if not check_telephone(message.text):
        await message.answer(f'Номер телефона введен некорректно. Повторите ввод (только цифрами, например "89995550101")')
        return
    data = await state.get_data()
    await add_user_to_db(message.from_user.id, data['name'], message.from_user.first_name, message.text)
    await message.answer(f'Данные сохранены! Ваши данные: \nФИО - {data["name"]} \nномер телефона - {message.text} \nваш id = {message.from_user.id}')
    await message.answer(f'✅ Отлично, регистрация завершена! Теперь вы готовы открыть для себя мир уникальных и нестандартных вакансий. \n💥 Нажмите на кнопку "Меню", чтобы заполнить свою анкету и начать искать работу или сотрудников.')
    await state.clear()  # Обязательно очищаем состояние

"""Обработчик команды /start. Запрашивает у пользователя ФИО."""
@dp.message(CommandStart(), State(None))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if user:  # Если пользователь уже зарегистрирован
        await message.answer(f"С возвращением, {message.from_user.first_name}! Вы уже зарегистрированы.\n\nРады вас видеть снова!")
        await message.answer("Выберите действия, например, /menu1 или /menu2 для начала работы с ботом.")
    else:  # Если пользователь новый
        data = await state.get_data()
        if "start_shown" not in data:  # Проверяем, показывали ли приветственное сообщение
            await message.answer(
                "💼 Добро пожаловать!\nЭто первый в мире бот с нешаблонными вакансиями. "
                "Благодаря нашим уникальным функциям соискатели смогут найти работу своей мечты, "
                "а работодатели — по-настоящему профессиональных специалистов! "
                "Начните свой путь с нами уже сегодня :)\n\n"
                "Основные команды:\n\n"
                "/start — запустите бота и зарегистрируйтесь (если ещё не сделали), "
                "это откроет доступ ко всем функциям бота.\n"
                "/menu1 — меню с основными функциями для соискателей и работодателей.\n"
                "/menu2 — меню для помощи, отправки отзывов и получения информации о боте.\n\n"
                "Желаем удачи в поиске! 🤗\n\n"
                "Чтобы продолжить, введите /start ещё раз."
            )
            await state.update_data(start_shown=True)  # Запоминаем, что приветствие уже показано
            return  # Останавливаем выполнение, чтобы не переходить к регистрации

        # Если пользователь уже второй раз ввел /start — начинаем регистрацию
        await message.answer(f'Итак, {message.from_user.first_name}! Для начала зарегистрируемся.\nВведите ваше ФИО:')
        await state.set_state(Form.name)  # Переход к состоянию ввода ФИО

# Обработчик команды для отправки обычной клавиатуры
@dp.message(Command("menu1"), State(None))
async def cmd_menu1(message: Message):
    """Обработчик команды для отправки обычной клавиатуры."""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🔍 Начать поиск"))
    builder.add(KeyboardButton(text="🙌 Мои мэтчи"))
    builder.add(KeyboardButton(text="🪪 Посмотреть профиль"))
    builder.add(KeyboardButton(text="📝 Заполнить анкету"))
    builder.add(KeyboardButton(text="ℹ️ О боте"))
    builder.adjust(2, 2, 1)
    keyboard = builder.as_markup(resize_keyboard=True, one_time_keyboard=True)
    await message.answer("Главное меню. Выберите действие:", reply_markup=keyboard)

@dp.message(Command("menu2"))
async def cmd_menu2(message: Message):
    """Обработчик команды для отправки обычной клавиатуры."""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🛠️ Написать в поддержку"))
    builder.add(KeyboardButton(text="💭 Оставить отзыв"))
    builder.add(KeyboardButton(text="ℹ️ О боте"))
    keyboard = builder.as_markup(resize_keyboard=True)
    await message.answer("Меню настроек и помощи. Выберите действие:", reply_markup=keyboard)

# КНОПКА 1 "🔍 Начать поиск"
@dp.message(F.text == "🔍 Начать поиск")
async def meditation_menu(message: Message):
    """Отправка клавиатуры с выбором медитации."""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Дизлайк"))
    builder.add(KeyboardButton(text="Лайк"))
    builder.add(KeyboardButton(text="Лайк с сообщением"))
    builder.add(KeyboardButton(text="Закончить"))
    builder.add(KeyboardButton(text="🔙 Вернуться в меню"))
    keyboard = builder.as_markup(resize_keyboard=True)

    await message.answer('✨ В будущем здесь будет множество вакансий ✨ \n\nА пока можно тыкнуть только на "🔙 Вернуться в меню" :)', reply_markup=keyboard)

# Ответ на команду "Вернуться в меню"
@dp.message(F.text == "🔙 Вернуться в меню")
async def return_to_menu(message: Message):
    """Возвращаем пользователя в основное меню."""
    await cmd_menu1(message)
# КОНЕЦ КНОПКИ 1 "🔍 Начать поиск"

# КНОПКА 2 "🙌 Мои мэтчи"
# Клавиатура для выбора мотивационных цитат
category_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Работа №1, компания A")],
        [KeyboardButton(text="Работа №2, компания B")],
        [KeyboardButton(text="Работа №3, компания C")],
        [KeyboardButton(text="Работа №N, компания N")],
        [KeyboardButton(text="🔙 Вернуться в меню")]
    ],
    resize_keyboard=True
)

# Обработчик кнопки для начала подписки
@dp.message(lambda message: message.text == "🙌 Мои мэтчи")
async def handle_motivation_button(message: types.Message):
    # Предложим пользователю выбрать категорию мотивации
    await message.answer('✨ В будущем здесь будет множество компаний, у которых с вами мэтч✨ \n\nА пока можно тыкнуть только на "🔙 Вернуться в меню" :)', reply_markup=category_keyboard)

@dp.message(lambda message: message.text == "🔙 Вернуться в меню")
async def return_to_menu(message: Message):
    """Возвращаем пользователя в основное меню."""
    await cmd_menu1(message)
# КОНЕЦ КНОПКИ 2 "🙌 Мои мэтчи"

# КНОПКА "🪪 Посмотреть профиль
# Функция загрузки данных о пользователе (описание)
def load_profile_from_file(user_id):
    """Загрузка описания профиля пользователя из файла"""
    file_name = f'about_{user_id}.txt'  # Имя файла с описанием профиля
    if os.path.exists(file_name):
        with open(file_name, 'r', encoding='utf-8') as file:
            return file.read()
    return None  # Если файл не существует, возвращаем None


# Функция загрузки скиллов пользователя
def load_skills_from_file(user_id):
    """Загрузка скиллов пользователя из файла"""
    file_name = f'skills_{user_id}.json'  # Имя файла с скиллами
    if os.path.exists(file_name):
        with open(file_name, 'r', encoding='utf-8') as file:
            try:
                skills = json.load(file)
                # Проверка на корректность данных
                for skill in skills:
                    if 'skill' not in skill or 'note' not in skill:
                        raise ValueError(f"Скилл {skill} некорректен, отсутствуют необходимые данные.")
                return skills
            except json.JSONDecodeError:
                print(f"Ошибка при чтении JSON из файла {file_name}.")
            except ValueError as e:
                print(e)
    return []  # Если файл не существует или произошла ошибка, возвращаем пустой список


# Стейты FSM
class ProfileStates(StatesGroup):
    waiting_for_profile_action = State()  # Ожидание действия: описание или скиллы
    waiting_for_skill = State()  # Ожидание выбора скилла

# Обработчик кнопки "🪪 Посмотреть профиль"
@dp.message(F.text == "🪪 Посмотреть профиль")
async def view_profile(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    # Загружаем описание профиля
    profile = load_profile_from_file(user_id)
    if not profile:
        await message.answer("❗ У вас нет заполненного профиля.")
        return

    # Загружаем скиллы
    skills = load_skills_from_file(user_id)

    # Создаем кнопки для выбора: описание или скиллы
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="1️⃣ Посмотреть описание"))
    if skills:
        builder.add(KeyboardButton(text="2️⃣ Посмотреть скиллы"))
    builder.add(KeyboardButton(text="🔙 Вернуться в меню"))
    keyboard = builder.as_markup(resize_keyboard=True)

    # Спрашиваем, что пользователь хочет посмотреть
    await message.answer("Что вы хотите посмотреть?", reply_markup=keyboard)
    await state.set_state(ProfileStates.waiting_for_profile_action)


# Обработчик выбора действия профиля: описание или скиллы
@dp.message(StateFilter(ProfileStates.waiting_for_profile_action))
async def process_profile_action(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    action = message.text

    if action == "1️⃣ Посмотреть описание":
        # Загружаем описание профиля
        profile = load_profile_from_file(user_id)
        if profile:
            await message.answer(f"📋 Информация о профиле:\n\n{profile}")
        else:
            await message.answer("❗ У вас нет заполненного профиля.")

    elif action == "2️⃣ Посмотреть скиллы":
        # Загружаем скиллы
        skills = load_skills_from_file(user_id)
        if not skills:
            await message.answer("❗ У вас нет скиллов, добавленных в профиль.")
            return

        # Создаем кнопки для каждого скилла
        builder = ReplyKeyboardBuilder()
        for skill in skills:
            skill_button = KeyboardButton(text=skill['skill'])
            builder.add(skill_button)

        builder.add(KeyboardButton(text="🔙 Вернуться в меню"))
        keyboard = builder.as_markup(resize_keyboard=True)

        # Отправляем меню с скиллами
        await message.answer("Выберите скилл для просмотра комментария:", reply_markup=keyboard)
        await state.set_state(ProfileStates.waiting_for_skill)

    else:
        await message.answer("❗ Неверный выбор. Попробуйте снова.")

# Обработчик выбора скилла для просмотра комментария
@dp.message(StateFilter(ProfileStates.waiting_for_skill))
async def view_skill_comment(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    skill_name = message.text

    # Загружаем скиллы
    skills = load_skills_from_file(user_id)
    skill = next((s for s in skills if s['skill'] == skill_name), None)

    if skill:
        # Отправляем комментарий к скиллу
        await message.answer(f"▫️ Уровень скилла от 1 до 10 '{skill_name}':  {skill['level']}")
        await message.answer(f"\n▫️ Комментарий к скиллу '{skill_name}':\n{skill['note']}")
    else:
        if message.text not in ["🔙 Вернуться в меню"]:  # Проверяем, не нажал ли пользователь кнопку
            await message.answer("❗ Скилл не найден. Вы вышли из режима выбора скиллов.")
            await state.clear()  # Очищаем состояние
        else:
            await message.answer("❗ Скилл не найден. Выберите другой скилл или нажмите '🔙 Вернуться в меню'.")

# КОНЕЦ КНОПКИ "🪪 Посмотреть профиль"

# Путь к файлам (пользовательский ID будет использоваться для создания уникальных файлов)
user_about_file = 'about_{}.txt'
user_skills_file = 'skills_{}.json'

# Состояния для заполнения анкеты
class Form1(StatesGroup):
    choosing_role = State()  # Выбор роли (Соискатель/Работодатель)
    waiting_for_education = State()  # Ввод образования
    waiting_for_experience = State()  # Ввод опыта работы
    waiting_for_format = State()  # Выбор формата работы (офис, удалёнка и т. д.)
    waiting_for_salary = State()  # Ввод ожидаемого дохода
    waiting_for_something = State()  # Ввод дополнительной информации о себе
    waiting_for_skill = State()  # Ввод названия скилла
    waiting_for_skill_level = State()  # Ввод уровня владения скиллом (1-10)
    waiting_for_skill_note = State()  # Ввод комментария к скиллу

# Функция для проверки существования анкеты пользователя
def check_existing_profile(user_id):
    return os.path.exists(user_about_file.format(user_id))


# Кнопки выбора типа анкеты
async def show_role_selection(message: Message):
    user_id = message.from_user.id
    builder = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔶 Соискатель", callback_data="applicant")],
        [InlineKeyboardButton(text="🔷 Работодатель", callback_data="employer")]
    ])

    #if check_existing_profile(user_id):
        #builder.inline_keyboard.append([InlineKeyboardButton(text="Заполнить заново", callback_data="reset")])

    builder.inline_keyboard.append([InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="menu2")])

    await message.answer("Выберите, кто вы:", reply_markup=builder)


@dp.message(F.text == "📝 Заполнить анкету")
async def fill_form(message: Message, state: FSMContext):
    await show_role_selection(message)
    await state.set_state(Form1.choosing_role)

# КНОПКА СОИСКАТЕЛЬ
@dp.callback_query(F.data == "applicant")
async def applicant_selected(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id

    # Сохраняем статус в данных
    await state.update_data(role="Соискатель")

    if check_existing_profile(user_id):
        with open(user_about_file.format(user_id), 'r', encoding='utf-8') as file:
            profile_info = file.read()
        await call.message.answer(f"Ваш профиль уже заполнен:\n\n{profile_info}",
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                      [InlineKeyboardButton(text="Заполнить заново", callback_data="reset")]
                                  ]))
        # Создаём кнопку "Вернуться в меню"
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Вернуться в меню")]],
            resize_keyboard=True
        )

        await call.message.answer("Либо вернитесь назад:", reply_markup=keyboard)

        return

    await call.message.answer("📚 Введите ваше образование:")
    await state.set_state(Form1.waiting_for_education)


@dp.callback_query(F.data == "reset")
async def reset_profile(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id

    # Удаляем старые файлы
    about_path = user_about_file.format(user_id)
    skills_path = user_skills_file.format(user_id)

    if os.path.exists(about_path):
        os.remove(about_path)
    if os.path.exists(skills_path):
        os.remove(skills_path)

    await call.message.answer("🗑 Ваш профиль удален. Заполните его заново.")
    await applicant_selected(call, state)


@dp.message(Form1.waiting_for_education)
async def process_education(message: Message, state: FSMContext):
    await state.update_data(education=message.text)
    await message.answer("💼 Опишите ваш опыт работы:")
    await state.set_state(Form1.waiting_for_experience)


@dp.message(Form1.waiting_for_experience)
async def process_experience(message: Message, state: FSMContext):
    await state.update_data(experience=message.text)
    await message.answer("📝 Добавьте дополнительную информацию о себе:")
    await state.set_state(Form1.waiting_for_something)


@dp.message(Form1.waiting_for_something)
async def process_experience(message: Message, state: FSMContext):
    await state.update_data(experience=message.text)

    # Добавляем вопрос про формат работы
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Офис", callback_data="format_office")],
        [InlineKeyboardButton(text="Гибрид", callback_data="format_hybrid")],
        [InlineKeyboardButton(text="Удалённо", callback_data="format_remote")],
        [InlineKeyboardButton(text="На проект", callback_data="format_project")]
    ])

    await message.answer("🏢 Какой формат работы вам больше всего подходит?", reply_markup=keyboard)
    await state.set_state(Form1.waiting_for_format)


@dp.callback_query(Form1.waiting_for_format)
async def process_format(call: CallbackQuery, state: FSMContext):
    format_mapping = {
        "format_office": "Офис",
        "format_hybrid": "Гибрид",
        "format_remote": "Удалённо",
        "format_project": "На проект"
    }
    selected_format = format_mapping.get(call.data, "Неизвестно")

    await state.update_data(preferred_format=selected_format)
    await call.message.answer("💰 Введите ваш ожидаемый доход:")
    await state.set_state(Form1.waiting_for_salary)


@dp.message(Form1.waiting_for_salary)
async def process_salary(message: Message, state: FSMContext):
    await state.update_data(salary=message.text)

    data = await state.get_data()
    user_id = message.from_user.id

    # Сохраняем данные в файл about_{user_id}.txt
    with open(user_about_file.format(user_id), 'w', encoding='utf-8') as file:
        file.write(
            f"🔸 Статус: {data.get('role')}\n"
            f"🔸 Образование: {data['education']}\n"
            f"🔸 Опыт работы: {data['experience']}\n"
            f"🔸 Формат работы: {data['preferred_format']}\n"
            f"🔸 Ожидаемый доход: {data['salary']}\n"
        )

    await message.answer("✅ Раздел о себе заполнен! Теперь добавьте свои скиллы.")
    await message.answer("Введите название скилла:")
    await state.set_state(Form1.waiting_for_skill)

@dp.message(Form1.waiting_for_skill)
async def process_skill(message: Message, state: FSMContext):
    await state.update_data(skill=message.text)
    if not message.text.lower() == 'готово':
        await message.answer("🔢 Оцените уровень владения этим скиллом (1-10):")
        await state.set_state(Form1.waiting_for_skill_level)
    else:
        await finish_profile(message, state)

@dp.message(Form1.waiting_for_skill_level)
async def process_skill_level(message: Message, state: FSMContext):
    if not message.text.isdigit() or not (1 <= int(message.text) <= 10):
        await message.answer("❌ Введите число от 1 до 10")
        return
    await state.update_data(skill_level=message.text)
    await message.answer("💬 Добавьте комментарий к скиллу (или напишите '-' если нет):")
    await state.set_state(Form1.waiting_for_skill_note)

@dp.message(Form1.waiting_for_skill_note)
async def process_skill_note(message: Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    skill_entry = {
        "skill": data["skill"],
        "level": data["skill_level"],
        "note": message.text
    }
    file_path = user_skills_file.format(user_id)
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as file:
            skills = json.load(file)
    else:
        skills = []
    skills.append(skill_entry)
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(skills, file, ensure_ascii=False, indent=4)
    await message.answer("✅ Скилл добавлен! Введите следующий или напишите 'Готово' для завершения.")
    await state.set_state(Form1.waiting_for_skill)

# Обработчик для слова "Готово"
@dp.message(Form1.waiting_for_skill)
async def finish_profile(message: Message, state: FSMContext):
    if message.text.lower() == 'готово':
        user_id = message.from_user.id
        data = await state.get_data()

        # Получаем данные пользователя из БД
        user = await get_user(user_id)
        if user:
            last_name, first_name, telephone_number = user[1], user[2], user[3]  # Распаковка данных
        else:
            last_name, first_name, telephone_number = "Неизвестно", "Неизвестно", "Не указан"

        # Собираем данные анкеты
        profile_info = f"ФИО: {last_name} \nТелефон: {telephone_number}\n"
        profile_info += f"🔸 Статус: {data.get('role')}\n"
        profile_info += f"🔸 Образование: {data.get('education')}\n"
        profile_info += f"🔸 Опыт работы: {data.get('experience')}\n"
        profile_info += f"🔸 Формат работы: {data.get('work_format')}\n"  # Добавлен формат работы
        profile_info += f"🔸 Ожидаемый доход: {data.get('expected_salary')}\n"  # Добавлена ожидаемая зарплата

        profile_info += "    \nСкиллы:\n"

        # Собираем список скиллов
        skills_file = user_skills_file.format(user_id)
        if os.path.exists(skills_file):
            with open(skills_file, 'r', encoding='utf-8') as file:
                skills = json.load(file)
                for skill in skills:
                    profile_info += f"🔸 {skill['skill']} (Уровень:  {skill['level']}) - {skill['note']}\n"

        # Создаём кнопку "Вернуться в меню"
        keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Вернуться в меню")]],
            resize_keyboard=True
        )

        # Выводим информацию о профиле
        await message.answer(f"Ваш профиль завершен, {first_name}! Вот ваши данные:\n\n{profile_info}", reply_markup=keyboard)

        # Завершаем состояние и очищаем данные анкеты
        await state.clear()

# Обработчик для кнопки "Вернуться в меню"
@dp.message(F.text == "🔙 Вернуться в меню")
async def back_to_menu(message: Message):
    await cmd_menu1(message)
# КОНЕЦ КНОПКИ СОИСКАТЕЛЬ

# КНОПКА РАБОТАДАТЕЛЬ
# Состояния для заполнения анкеты работодателя
class Form2(StatesGroup):
    choosing_role = State()  # Выбор роли (Соискатель/Работодатель)
    waiting_for_company_description2 = State()  # Описание компании
    waiting_for_team_description2 = State()  # Описание команды/работы
    waiting_for_format2 = State()  # Выбор формата работы (офис, удалёнка и т. д.)
    waiting_for_salary2 = State()  # Ввод предлагаемой зарплаты
    waiting_for_skill2 = State()  # Ввод названия скилла
    waiting_for_skill_level2 = State()  # Ввод уровня владения скиллом (1-10)
    waiting_for_skill_note2 = State()  # Ввод комментария к скиллу

@dp.callback_query(F.data == "employer")
async def employer_selected(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id

    # Сохраняем статус в данных
    await state.update_data(role="Работодатель")

    if check_existing_profile(user_id):
        with open(user_about_file.format(user_id), 'r', encoding='utf-8') as file:
            profile_info2 = file.read()
        await call.message.answer(f"Ваш профиль уже заполнен:\n\n{profile_info2}",
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                      [InlineKeyboardButton(text="Заполнить заново", callback_data="reset2")]
                                  ]))
        # Создаём кнопку "Вернуться в меню"
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Вернуться в меню")]],
            resize_keyboard=True
        )

        await call.message.answer("Либо вернитесь назад:", reply_markup=keyboard)
        return
    await call.message.answer("🏢 Введите описание вашей компании:")
    await state.set_state(Form2.waiting_for_company_description2)


@dp.callback_query(F.data == "reset2")
async def reset2_profile(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id

    # Удаляем старые файлы
    about_path = user_about_file.format(user_id)
    skills_path = user_skills_file.format(user_id)

    if os.path.exists(about_path):
        os.remove(about_path)
    if os.path.exists(skills_path):
        os.remove(skills_path)

    await call.message.answer("🗑 Ваш профиль удален. Заполните его заново.")
    await employer_selected(call, state)


@dp.message(Form2.waiting_for_company_description2)
async def process_company_description2(message: Message, state: FSMContext):
    await state.update_data(company_description2=message.text)
    await message.answer("💼 Введите описание команды или работы:")
    await state.set_state(Form2.waiting_for_team_description2)


@dp.message(Form2.waiting_for_team_description2)
async def process_team_description2(message: Message, state: FSMContext):
    await state.update_data(team_description2=message.text)

    # Добавляем вопрос про формат работы
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Офис", callback_data="format_office2")],
        [InlineKeyboardButton(text="Гибрид", callback_data="format_hybrid2")],
        [InlineKeyboardButton(text="Удалённо", callback_data="format_remote2")],
        [InlineKeyboardButton(text="На проект", callback_data="format_project2")]
    ])

    await message.answer("🏢 Какой формат работы предлагается?", reply_markup=keyboard)
    await state.set_state(Form2.waiting_for_format2)


@dp.callback_query(Form2.waiting_for_format2)
async def process_format2(call: CallbackQuery, state: FSMContext):
    format_mapping = {
        "format_office2": "Офис",
        "format_hybrid2": "Гибрид",
        "format_remote2": "Удалённо",
        "format_project2": "На проект"
    }
    selected_format = format_mapping.get(call.data, "Неизвестно")

    await state.update_data(preferred_format2=selected_format)
    await call.message.answer("💰 Введите предлагаемую зарплату:")
    await state.set_state(Form2.waiting_for_salary2)

@dp.message(Form2.waiting_for_salary2)
async def process_salary2(message: Message, state: FSMContext):
    await state.update_data(salary2=message.text)

    data = await state.get_data()
    user_id = message.from_user.id

    # Сохраняем данные в файл about_{user_id}.txt
    with open(user_about_file.format(user_id), 'w', encoding='utf-8') as file:
        file.write(
            f"🔹 Статус: {data.get('role')}\n" 
            f"🔹 Описание компании: {data['company_description2']}\n"
            f"🔹 Описание команды/работы: {data['team_description2']}\n"
            f"🔹 Формат работы: {data['preferred_format2']}\n"
            f"🔹 Предлагаемая зарплата: {data['salary2']}\n"
        )

    await message.answer("✅ Раздел о компании и вакансии заполнен! Теперь добавьте скиллы, которые необходимы для работы.")
    await message.answer("Введите название скилла:")
    await state.set_state(Form2.waiting_for_skill2)


@dp.message(Form2.waiting_for_skill2)
async def process_skill2(message: Message, state: FSMContext):
    await state.update_data(skill=message.text)
    if not message.text.lower() == 'готово':
        await message.answer("🔢 Оцените уровень владения этим скиллом (1-10):")
        await state.set_state(Form2.waiting_for_skill_level2)
    else:
        await finish_profile2(message, state)


@dp.message(Form2.waiting_for_skill_level2)
async def process_skill_level2(message: Message, state: FSMContext):
    if not message.text.isdigit() or not (1 <= int(message.text) <= 10):
        await message.answer("❌ Введите число от 1 до 10")
        return
    await state.update_data(skill_level=message.text)
    await message.answer("💬 Добавьте комментарий к скиллу (или напишите '-' если нет):")
    await state.set_state(Form2.waiting_for_skill_note2)


@dp.message(Form2.waiting_for_skill_note2)
async def process_skill_note2(message: Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    skill_entry = {
        "skill": data["skill"],
        "level": data["skill_level"],
        "note": message.text
    }
    file_path = user_skills_file.format(user_id)
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as file:
            skills = json.load(file)
    else:
        skills = []
    skills.append(skill_entry)
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(skills, file, ensure_ascii=False, indent=4)
    await message.answer("✅ Скилл добавлен! Введите следующий или напишите 'Готово' для завершения.")
    await state.set_state(Form2.waiting_for_skill2)


# Обработчик для слова "Готово"
@dp.message(Form2.waiting_for_skill2)
async def finish_profile2(message: Message, state: FSMContext):
    if message.text.lower() == 'готово':
        user_id = message.from_user.id
        data = await state.get_data()

        # Получаем данные пользователя из БД
        user = await get_user(user_id)
        if user:
            last_name, first_name, telephone_number = user[1], user[2], user[3]  # Распаковка данных
        else:
            last_name, first_name, telephone_number = "Неизвестно", "Неизвестно", "Не указан"

        # Собираем данные анкеты
        profile_info2 = f"ФИО: {last_name} \nТелефон: {telephone_number}\n"
        profile_info2 += f"🔹 Статус: {data.get('role')}\n"
        profile_info2 += f"🔹 Описание компании: {data.get('company_description2')}\n"
        profile_info2 += f"🔹 Описание команды/работы: {data.get('team_description2')}\n"
        profile_info2 += f"🔹 Формат работы: {data.get('preferred_format2')}\n"  # Добавлен формат работы
        profile_info2 += f"🔹 Предлагаемая зарплата: {data.get('salary2')}\n"  # Добавлена предлагаемая зарплата

        profile_info2 += "    \nНеобходимые скиллы:\n"

        # Собираем список скиллов
        skills_file = user_skills_file.format(user_id)
        if os.path.exists(skills_file):
            with open(skills_file, 'r', encoding='utf-8') as file:
                skills = json.load(file)
                for skill in skills:
                    profile_info2 += f"🔹 {skill['skill']} (Уровень:  {skill['level']}) - {skill['note']}\n"

        # Создаём кнопку "Вернуться в меню"
        keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Вернуться в меню")]],
            resize_keyboard=True
        )

        # Выводим информацию о профиле
        await message.answer(f"Ваш профиль завершен, {first_name}! Вот ваши данные:\n\n{profile_info2}", reply_markup=keyboard)

        # Завершаем состояние и очищаем данные анкеты
        await state.clear()


# Обработчик для кнопки "Вернуться в меню"
@dp.message(F.text == "🔙 Вернуться в меню")
async def back_to_menu(message: Message):
    await cmd_menu1(message)

@dp.callback_query(F.data == "menu2")
async def back_to_menu(message: Message):
    await cmd_menu1(message)
# КОНЕЦ КНОПКИ РАБОТАДАТЕЛЬ

# КНОПКА "ℹ️ О боте"
@dp.message(F.text == "ℹ️ О боте")
async def question(message: Message):
    """Обработка вопроса пользователя."""
    await message.answer("ℹ️ О боте: \n\nTinderJob — это ваш помощник в поиске идеальной работы и настоящих профессионалов. \nМы создали его, чтобы вы могли:\n\n▪️ Легко и без лишних усилий подобрать работу вашей мечты.\n▪️ Найти лучших специалистов, которые будут работать с увлечением и удовольствием.\n\n📌 Основные команды:\n\n/start — регистрация и начало вашего пути к идеальной работе или сотруднику.\n/menu1 — Главное меню для поиска работы и просмотра ваших мэтчей.\n/menu2 — Меню настроек и помощи, включая поддержку и обратную связь.")
# КОНЕЦ КНОПКА "ℹ️ О боте"

# КНОПКА "🛠️ Написать в поддержку"
@dp.message(F.text == "🛠️ Написать в поддержку")
async def meditation_menu(message: Message):
    """Отправка клавиатуры с выбором медитации."""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🔙 Вернуться в меню"))
    keyboard = builder.as_markup(resize_keyboard=True)
    await message.answer('✨ В будущем здесь появится возможность писать сообщения ✨ \n\nА пока нужно тыкнуть на "🔙 Вернуться в меню" :)', reply_markup=keyboard)
# КНОПКА КНОПКИ "🛠️ Написать в поддержку"

# КНОПКА "💭 Оставить отзыв"
# Путь к файлу для хранения отзывов
FEEDBACK_FILE = 'feedbacks.json'
class UserStates(StatesGroup):
    leaving_feedback = State()  # Состояние для оставления отзыва
# Функция для добавления отзыва в JSON
def add_to_json(file_path, data):
    """Добавить отзыв в JSON файл"""
    try:
        # Проверка, существует ли файл
        if os.path.exists(file_path):
            # Если файл существует, загружаем старые отзывы
            with open(file_path, 'r', encoding='utf-8') as file:
                feedbacks = json.load(file)
        else:
            # Если файла нет, создаем новый список для отзывов
            feedbacks = []
        # Добавляем новый отзыв
        feedbacks.append(data)
        # Записываем обновленные данные обратно в файл
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(feedbacks, file, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Error while saving feedback to JSON: {e}")
        raise

@dp.message(F.text == "💭 Оставить отзыв")
async def feedback_prompt(message: types.Message, state: FSMContext):
    await state.set_state(UserStates.leaving_feedback)
    await message.answer(
        "Пожалуйста, напишите ваш отзыв или предложение:",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text="Отмена")]],
            resize_keyboard=True
        )
    )

@dp.message(UserStates.leaving_feedback)
async def process_feedback(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await state.clear()
        await message.answer("Отправка отзыва отменена.")
        await cmd_menu1(message)
        return

    try:
        feedback = message.text
        # Формируем данные для сохранения
        data = {"user_id": str(message.from_user.id), "feedback": feedback}

        # Добавляем отзыв в JSON
        add_to_json(FEEDBACK_FILE, data)

        await message.answer(
            "Спасибо большое за ваш отзыв! 🫶\n"
            "Мы ценим ваше мнение и постараемся стать лучше!",
        )
        # Возвращаем пользователя в главное меню
        await cmd_menu1(message)

    except Exception as e:
        logging.error(f"Error saving feedback: {e}")
        await message.answer(
            "Произошла ошибка при сохранении отзыва. Пожалуйста, попробуйте позже.",
            await cmd_menu1(message)
        )
    finally:
        await state.clear()
# КОНЕЦ КНОПКА "💭 Оставить отзыв"

# Обработчик произвольного текста
@dp.message()
async def handle_message(message: Message, state: FSMContext):
    """Ответ на произвольный текст от пользователя."""

    # Получаем данные из состояния
    user_data = await state.get_data()

    # Проверяем, завершён ли разговор
    if user_data.get("conversation_ended"):
        # Если разговор завершён, игнорируем произвольные сообщения
        await message.answer(f'Уважаемый {message.from_user.first_name}, нельзя писать произвольный текст! \n\nЕсли возникла какая-то проблема, напишите нам в поддержку:\nдля этого нажмите на кнопку "🛠️ Написать в поддержку". \n\nМы обязательно вам поможем 💌')
    else:
        # Проверяем, есть ли активное состояние у пользователя
        current_state = await state.get_state()

        # Если состояние пустое, это значит, что бот не ожидает ввода данных
        if current_state is None:
            await message.answer(f'Уважаемый {message.from_user.first_name}, нельзя писать произвольный текст! \n\nЕсли возникла какая-то проблема, напишите нам в поддержку:\nдля этого нажмите на кнопку "🛠️ Написать в поддержку". \n\nМы обязательно вам поможем 💌')
        else:
            # Если состояние активно, значит, бот ожидает конкретный ответ
            return

# Запуск бота и настройка команд
async def start_bot():
    """Настройка команд для бота."""
    commands = [
        BotCommand(command='menu1', description='Главное меню'),
        BotCommand(command='menu2', description='Меню настроек и помощи')
    ]
    await bot.set_my_commands(commands, BotCommandScopeDefault())

# Основная асинхронная функция
async def main():
    """Запуск бота."""
    await create_db()  # Создаем таблицу при запуске
    dp.startup.register(start_bot)
    try:
        print("Бот запущен...")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())  # Запуск бота в режиме опроса
    except asyncio.CancelledError:
        print("Задача была отменена. Завершаем работу бота...")
    finally:
        await bot.session.close()
        print("Бот остановлен")

# Запуск основной асинхронной функции
asyncio.run(main())