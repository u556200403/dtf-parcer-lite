import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"
TELEGRAM_TOKEN = "ADD_TOKEN"

SECTIONS = {
    "popular": "/popular",
    "cinema": "/cinema",
    "games": "/games",
    "music": "/music",
    "gamedev": "/gamedev"
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Популярное", callback_data="popular")],
        [InlineKeyboardButton("Кино и сериалы", callback_data="cinema")],
        [InlineKeyboardButton("Игры", callback_data="games")],
        [InlineKeyboardButton("Музыка", callback_data="music")],
        [InlineKeyboardButton("Gamedev", callback_data="gamedev")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите раздел:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    section = query.data
    if section in SECTIONS:
        await query.edit_message_text(f"Выбран раздел: {section}. Теперь введите тему для поиска:")
        context.user_data["current_section"] = section
    else:
        await query.edit_message_text("Неизвестный раздел")

async def handle_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "current_section" not in context.user_data:
        await update.message.reply_text("Сначала выберите раздел с помощью команды /start")
        return
    
    topic = update.message.text
    section = context.user_data["current_section"]
    
    await update.message.reply_text(f"Ищу новости по теме '{topic}' в разделе '{section}'...")
    
    try:
        all_news = scrape_dtf_news_with_scroll(SECTIONS[section])
        
        filtered = [
            n for n in all_news 
            if topic.lower() in n.lower()
        ]
        
        if not filtered:
            await update.message.reply_text(
                f"Не найдено новостей по теме '{topic}' в разделе '{section}'. Попробуйте другую тему."
            )
            return
        
        summary = await summarize_with_ollama(filtered[:5], topic)
        await update.message.reply_text(summary, disable_web_page_preview=True)
        
    except Exception as e:
        await update.message.reply_text(f"Произошла ошибка: {str(e)}")

async def summarize_with_ollama(news_list: list[str], topic: str) -> str:
    if not news_list:
        return f"Не найдено новостей по теме '{topic}'."
    
    prompt = (
        f"Сделай краткую выжимку из следующих новостей по теме '{topic}'. "
        "Если новости не совсем соответствуют теме, укажи это. "
        "Отвечай на русском языке. Формат:\n"
        "1. [Заголовок](ссылка) - краткое описание\n"
        "2. ...\n\n"
        "Новости:\n\n"
    )
    prompt += "\n\n".join(news_list)

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }
    )

    if response.ok:
        result = response.json()
        return result.get("response", "Не удалось получить ответ от модели.")
    return "Ошибка при подключении к серверу."

def scrape_dtf_news_with_scroll(section_url: str) -> list[str]:
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080")
    
    driver = webdriver.Chrome(options=chrome_options)
    url = f"https://dtf.ru{section_url}"
    
    try:
        driver.get(url)
        time.sleep(2)
        
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0
        max_scroll_attempts = 5
        news_count = 0
        
        while scroll_attempts < max_scroll_attempts and news_count < 50:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            scroll_attempts += 1
            
            soup = BeautifulSoup(driver.page_source, "html.parser")
            news_count = len(soup.find_all("div", class_="content--short"))
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        news_items = []
        
        content_blocks = soup.find_all("div", class_="content--short", limit=50)
        
        for block in content_blocks:
            title_block = block.find("div", class_="content-title")
            if not title_block:
                continue
                
            title = title_block.text.strip()
            
            link_block = block.find("a", class_="content__link")
            if not link_block or "href" not in link_block.attrs:
                continue
                
            link = "https://dtf.ru" + link_block["href"]
            
            text_block = block.find("div", class_="block-text")
            description = text_block.text.strip() if text_block else ""
            
            news_items.append(f"{title}\n{link}\n{description}")

        return news_items
        
    except Exception as e:
        print(f"Ошибка при загрузке данных: {e}")
        return []
    finally:
        driver.quit()

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_topic))
    
    print("Бот работает")
    app.run_polling()

if __name__ == "__main__":
    main()