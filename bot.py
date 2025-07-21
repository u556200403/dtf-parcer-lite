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
import urllib.parse
from datetime import datetime

API_ENDPOINT = "http://127.0.0.1:11434/api/generate"
MODEL_NAME = "llama3"
BOT_TOKEN = "YOUR_TOKEN"

CATEGORIES = {
    "popular": "/popular",
    "cinema": "/cinema",
    "games": "/games",
    "music": "/music",
    "gamedev": "/gamedev"
}

async def init_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu = [
        [InlineKeyboardButton("Популярное", callback_data="popular")],
        [InlineKeyboardButton("Кино и сериалы", callback_data="cinema")],
        [InlineKeyboardButton("Игры", callback_data="games")],
        [InlineKeyboardButton("Музыка", callback_data="music")],
        [InlineKeyboardButton("Gamedev", callback_data="gamedev")],
        [InlineKeyboardButton("Самые популярные посты по теме", callback_data="site_search")]
    ]
    await update.message.reply_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(menu))

async def process_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    category = query.data
    if category in CATEGORIES:
        await query.edit_message_text(f"Выбрана категория: {category}. Введите тему:")
        context.user_data["current_category"] = category
    elif category == "site_search":
        await query.edit_message_text("Введите поисковый запрос:")
        context.user_data["search_type"] = "site"
    else:
        await query.edit_message_text("Ошибка")

async def process_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "current_category" not in context.user_data and "search_type" not in context.user_data:
        await update.message.reply_text("Сначала выберите категорию")
        return
    
    search_query = update.message.text
    
    if "search_type" in context.user_data and context.user_data["search_type"] == "site":
        await update.message.reply_text(f"Поиск: '{search_query}'...")
        try:
            results = perform_site_search(search_query)
            
            if not results:
                await update.message.reply_text("Ничего не найдено")
                return
            
            output = "Топ результатов:\n\n"
            for i, (title, url, views) in enumerate(results[:20], 1):
                output += f"{i}. [{title}]({url}) - 👁️ {views}\n"
            
            await update.message.reply_text(output, parse_mode="Markdown", disable_web_page_preview=True)
            
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {str(e)}")
        finally:
            if "search_type" in context.user_data:
                del context.user_data["search_type"]
    else:
        category = context.user_data["current_category"]
        await update.message.reply_text(f"Поиск: '{search_query}' в '{category}'...")
        
        try:
            news_items = get_category_news(CATEGORIES[category])
            
            filtered = [n for n in news_items if search_query.lower() in n.lower()]
            
            if not filtered:
                await update.message.reply_text("Ничего не найдено")
                return
            
            summary = await generate_summary(filtered[:5], search_query)
            await update.message.reply_text(summary, disable_web_page_preview=True)
            
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {str(e)}")

def perform_site_search(query: str) -> list:
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920x1080")
    
    driver = webdriver.Chrome(options=options)
    encoded_query = urllib.parse.quote(query)
    url = f"https://dtf.ru/discovery?q={encoded_query}"
    
    try:
        driver.get(url)
        time.sleep(3)
        
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        items = []
        
        for item in soup.find_all("div", class_="content--short"):
            title = item.find("div", class_="content-title")
            if not title:
                continue
            title = title.get_text(strip=True)
            
            link = item.find("a", class_="content__link")
            if not link or not link.get("href"):
                continue
            link = "https://dtf.ru" + link["href"]
            
            views = item.find("a", class_="comments-counter")
            if views:
                views = views.find("div", class_="content-footer-button__label")
                if views:
                    try:
                        views = int(views.get_text(strip=True))
                    except:
                        views = 0
                else:
                    views = 0
            else:
                views = 0
            
            date = item.find("time")
            if date and 'datetime' in date.attrs:
                try:
                    date_obj = datetime.strptime(date['datetime'], "%Y-%m-%dT%H:%M:%S.%fZ")
                    date_ts = date_obj.timestamp()
                except:
                    date_ts = time.time()
            else:
                date_ts = time.time()
            
            current_ts = time.time()
            hours_diff = (current_ts - date_ts) / 3600
            freshness = max(0, 1 - (hours_diff / 24))
            weight = views * (1 + freshness)
            
            items.append((title, link, views, date_ts, weight))
        
        items.sort(key=lambda x: x[4], reverse=True)
        return [(t, l, v) for t, l, v, _, _ in items]
        
    except Exception as e:
        print(f"Ошибка: {e}")
        return []
    finally:
        driver.quit()

async def generate_summary(items: list, query: str) -> str:
    if not items:
        return f"Не найдено по запросу '{query}'."
    
    prompt = f"Сделай краткую выжимку по теме '{query}'. Формат:\n1. [Заголовок](ссылка) - описание\n\nМатериалы:\n\n" + "\n\n".join(items)

    response = requests.post(
        API_ENDPOINT,
        json={
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False
        }
    )

    if response.ok:
        return response.json().get("response", "Ошибка")
    return "Ошибка соединения"

def get_category_news(category_url: str) -> list:
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920x1080")
    
    driver = webdriver.Chrome(options=options)
    url = f"https://dtf.ru{category_url}"
    
    try:
        driver.get(url)
        time.sleep(2)
        
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(5):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        results = []
        
        for item in soup.find_all("div", class_="content--short", limit=50):
            title = item.find("div", class_="content-title")
            if not title:
                continue
            title = title.text.strip()
            
            link = item.find("a", class_="content__link")
            if not link or "href" not in link.attrs:
                continue
            link = "https://dtf.ru" + link["href"]
            
            text = item.find("div", class_="block-text")
            text = text.text.strip() if text else ""
            
            results.append(f"{title}\n{link}\n{text}")

        return results
        
    except Exception as e:
        print(f"Ошибка: {e}")
        return []
    finally:
        driver.quit()

def start_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", init_bot))
    app.add_handler(CallbackQueryHandler(process_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text))
    
    print("Бот активен")
    app.run_polling()

if __name__ == "__main__":
    start_bot()