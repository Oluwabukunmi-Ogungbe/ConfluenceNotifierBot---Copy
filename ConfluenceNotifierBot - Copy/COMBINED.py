import os
import time
from datetime import datetime
from dotenv import find_dotenv, load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telethon import TelegramClient
import re
from collections import defaultdict
import logging
import asyncio
import sys
from contextlib import suppress
from httpx import Timeout
import logging
import nest_asyncio
from keep_alive import keep_alive

nest_asyncio.apply()

keep_alive()

PORT = 8443  # Render will provide the PORT environment variable

# Telegram bot configuration
dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

# Telethon client configuration
BOT_TOKEN = "7327291802:AAFPM911VQH5uyTX2uPG8j503NCt3r62yMs"#3os.getenv("BOT_TOKEN")
API_ID = 21202746#int(os.getenv("API_ID"))
API_HASH = "e700432294937e6925a83149ee7165a0"#os.getenv("API_HASH")

# Create Telethon client
telethon_client = TelegramClient('test', API_ID, API_HASH)

# Excluded token address
EXCLUDED_TOKEN = 'So11111111111111111111111111111112'

# Authorized users allowed to command the bot in THETRACKOORS group
AUTHORIZED_USERS = {'orehub1378', 'Kemoo1975', 'jeremi1234', 'Busiiiiii'}
# The THETRACKOORS group identifier
THETRACKOORS_CHAT_ID = -1002297141126  # Replace with actual chat ID for THETRACKOORS

# Global variable to indicate if THETRACKOORS is being monitored
is_tracking_thetrackoors = False

class MonitoringSession:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.is_monitoring = False
        self.multi_trader_tokens = {}
        self.previous_messages = []
        self.monitoring_task = None
        self.token_pump_types = {}
        self.token_market_caps = {}
        self.token_sol_amounts = {}
        self.token_timestamps = {}
        self.start_time = None
        self.round_start_time = None


async def initialize_telethon():
    global telethon_client
    telethon_client = TelegramClient('test', API_ID, API_HASH)
    await telethon_client.start()
    logging.info("Telethon client initialized and started")

async def check_authorization(update):
    """Check if the user is authorized to use the bot in the THETRACKOORS group"""
    user_username = update.effective_user.username

    # Check if the user is in AUTHORIZED_USERS and the chat is THETRACKOORS
    if update.effective_chat.id == THETRACKOORS_CHAT_ID:
        return user_username and user_username.lower() in {user.lower() for user in AUTHORIZED_USERS}
    
    return False  # Not authorized if not in THETRACKOORS group

def extract_market_cap(text):
    """Extract market cap value and unit from the message"""
    mc_pattern = r'(?:(?:MC|MCP):\s*\$?\s*([\d.]+)\s*([KkMm])?|\$?\s*([\d.]+)\s*([KkMm])?\s*(?=(?:MC|MCP)))'
    match = re.search(mc_pattern, text, re.IGNORECASE)

    if match:
        value = match.group(1) or match.group(3)
        unit = match.group(2) or match.group(4)

        try:
            value = float(value)
            # Standardize unit to uppercase
            if unit:
                unit = unit.upper()
            else:
                unit = 'K'  # Default to K if no unit specified
            return {'value': value, 'unit': unit}
        except ValueError:
            return None
    return None

def extract_sol_amount(text):
    """Extract the last number before 'SOL' in the text"""
    sol_pos = text.find('SOL')
    if sol_pos == -1:
        return None

    text_before_sol = text[:sol_pos]
    numbers = re.findall(r'[-+]?\d*\.\d+|\d+', text_before_sol)

    if numbers:
        try:
            return float(numbers[-1])
        except ValueError:
            return None
    return None

def has_pump_keywords(text):
    """Check if the message contains any pump-related keywords with case sensitivity for PUMP"""
    pump_match = any(pump_word in text for pump_word in ['PUMP', 'Pump'])
    other_keywords = any(keyword in text.lower() for keyword in ['pumpfun', 'raydium'])
    return pump_match or other_keywords

async def is_valid_buy_message(text):
    """Check if the message is a valid buy message with pump keywords"""
    if not has_pump_keywords(text):
        return False

    buy_pattern = r'(?:BUY|Buy|buy)'
    sell_pattern = r'(?:SELL|Sell|sell)'

    buy_matches = list(re.finditer(buy_pattern, text))
    sell_matches = list(re.finditer(sell_pattern, text))

    if not sell_matches:
        return bool(buy_matches)

    if buy_matches and sell_matches:
        first_buy_pos = buy_matches[0].start()
        first_sell_pos = sell_matches[0].start()
        return first_buy_pos < first_sell_pos

    return False

def extract_pump_type(text):
    """Extract pump type from the message with case sensitivity for PUMP"""
    if 'pumpfun' in text.lower():
        return 'PUMPFUN'
    elif 'raydium' in text.lower():
        return 'RAYDIUM'
    elif 'PUMP' in text or 'Pump' in text:
        return 'PUMPFUN'
    return None

def get_token_address(text, chat_link):
    """Extract token address based on the chat source"""
    solana_addresses = re.findall(r'[0-9A-HJ-NP-Za-km-z]{32,44}', text)
    if not solana_addresses:
        return None
        
    if 'Godeye_wallet_trackerBot' in chat_link:
        return solana_addresses[0]
    
    return solana_addresses[-1]

async def scrap_message(chat, session, context, limit=50):
    """Scrape messages and track token purchases"""
    async for message in telethon_client.iter_messages(chat, limit=limit):
        if message.text:
            text = message.text

            if not has_pump_keywords(text):
                continue

            if await is_valid_buy_message(text):
                trader_pattern = r'(?:TRADER|Trader|trader)\d+'
                trader_match = re.search(trader_pattern, text)
                token_address = get_token_address(text, chat)

                if trader_match and token_address:
                    trader = trader_match.group()

                    if token_address != EXCLUDED_TOKEN:
                        pump_type = extract_pump_type(text)
                        market_cap = extract_market_cap(text)
                        sol_amount = extract_sol_amount(text)
                        timestamp = message.date.timestamp()

                        if token_address not in session.multi_trader_tokens:
                            session.multi_trader_tokens[token_address] = set()
                            session.token_market_caps[token_address] = {}
                            session.token_sol_amounts[token_address] = {}
                            session.token_timestamps[token_address] = {}
                            if pump_type:
                                session.token_pump_types[token_address] = pump_type

                        session.multi_trader_tokens[token_address].add(trader)
                        if market_cap is not None:
                            session.token_market_caps[token_address][trader] = market_cap
                        if sol_amount is not None:
                            session.token_sol_amounts[token_address][trader] = sol_amount
                        session.token_timestamps[token_address][trader] = timestamp

                        if trader not in session.multi_trader_tokens[token_address]:
                            session.multi_trader_tokens[token_address][trader] = []
                        
                        # Add this buy to the trader's history
                        buy_info = {
                            'sol_amount': sol_amount,
                            'pump_type': pump_type,
                            'timestamp': timestamp,
                            'market_cap': market_cap
                        }
                        session.multi_trader_tokens[token_address][trader].append(buy_info)

                        # Only send a message if this is the second or more buy
                        if len(session.multi_trader_tokens[token_address][trader]) >= 2:
                            buys = session.multi_trader_tokens[token_address][trader]
                            message_lines = [f"{trader} bought {token_address} {len(buys)} times"]
                            
                            for idx, buy in enumerate(buys, 1):
                                sol_str = f"{buy['sol_amount']:.2f}" if buy['sol_amount'] else "Unknown"
                                pump_str = buy['pump_type'] if buy['pump_type'] else "Unknown"
                                message_lines.append(f"Buy {idx}: {sol_str} SOL on {pump_str}")
                            
                            message_to_send = "\n".join(message_lines)
                            await context.bot.send_message(chat_id=session.chat_id, text=message_to_send)


async def monitor_channels(context, session):
    """Monitor channels for a specific chat session"""
    global is_tracking_thetrackoors

    chat_limits = {
        'https://t.me/ray_silver_bot': 150,
        'https://t.me/handi_cat_bot': 300,
        'https://t.me/Wallet_tracker_solana_spybot': 75,
        'https://t.me/Godeye_wallet_trackerBot': 150,

        'https://t.me/GMGN_alert_bot': 150,
        'https://t.me/Solbix_bot': 300
    }

   

    while session.is_monitoring:

        session.round_start_time = time.time()

        async with telethon_client:
            for chat_link, limit in chat_limits.items():
                if chat_link == 'https://t.me/THETRACKOORS':
                    if is_tracking_thetrackoors:  # Only allow this when the group is being monitored
                        await scrap_message(chat_link, session, context, limit)

                # Personal chats are not allowed if THETRACKOORS is active
                if not is_tracking_thetrackoors:
                    await scrap_message(chat_link, session, context, limit)

        current_messages = []
        for address, traders in session.multi_trader_tokens.items():
            if len(traders) >= 2:
                latest_trader = max(traders, key=lambda t: session.token_timestamps[address].get(t, 0))
                pump_type = session.token_pump_types.get(address, "Unknown")
                sol_amount = session.token_sol_amounts[address].get(latest_trader)
                market_cap = session.token_market_caps[address].get(latest_trader)

                message = (
                    f"{len(traders)} traders bought {address}:\n"
                    f"last trader bought"
                )

                if sol_amount is not None:
                    message += f" {sol_amount:.1f} SOL"

                message += f" on {pump_type}"

                if market_cap is not None:
                    message += f" at MC: ${market_cap['value']:.2f}{market_cap['unit']}"

                current_messages.append(message)

        new_messages = [msg for msg in current_messages if msg not in session.previous_messages]

        round_duration = time.time() - session.round_start_time
        total_duration = time.time() - session.start_time

        timing_message = (
            f"\nRound Timing:\n"
            f"Round Duration: {round_duration:.2f} seconds\n"
            f"Total Running Time: {total_duration:.2f} seconds"
        )

        if new_messages:
            for message in new_messages:
                await context.bot.send_message(
                    chat_id=session.chat_id,
                    text=message
                )
            session.previous_messages = current_messages.copy()
        else:
            await context.bot.send_message(
                chat_id=session.chat_id,
                text="No new multiple-trader tokens found" + timing_message
            )

        await asyncio.sleep(1)
        if session.is_monitoring:
            pass
        else:
            final_duration = time.time() - session.start_time
            await context.bot.send_message(
                chat_id=session.chat_id,
                text=f"Monitoring stopped. Total running time: {final_duration:.2f} seconds"
            )
            break

async def start(update, context):
    """Start the message monitoring process for the THETRACKOORS group"""
    global is_tracking_thetrackoors
    chat_id = update.effective_chat.id

    # Check if user is authorized and the chat is THETRACKOORS
    if not await check_authorization(update):
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"You are not eligible to use the bot. Your username: {update.effective_user.username}"
        )
        return

    # Start monitoring session for THETRACKOORS group
    if chat_id in context.bot_data:
        session = context.bot_data[chat_id]
        
        if not session.is_monitoring:
            session.is_monitoring = True
            session.start_time = time.time()
            session.monitoring_task = asyncio.create_task(monitor_channels(context, session))
            await context.bot.send_message(
                chat_id=chat_id,
                text="Monitoring now started for THETRACKOORS."
            )
    else:
        context.bot_data[chat_id] = MonitoringSession(chat_id)
        session = context.bot_data[chat_id]
        session.is_monitoring = True
        session.start_time = time.time()
        session.monitoring_task = asyncio.create_task(monitor_channels(context, session))
        await context.bot.send_message(
            chat_id=chat_id,
            text="Monitoring started for THETRACKOORS."
        )

async def stop(update, context):
    """Stop the message monitoring process for the THETRACKOORS group"""
    global is_tracking_thetrackoors
    chat_id = update.effective_chat.id
    
    if chat_id in context.bot_data:
        session = context.bot_data[chat_id]
        if session.is_monitoring:
            session.is_monitoring = False
            if session.monitoring_task:
                session.monitoring_task.cancel()
            final_duration = time.time() - session.start_time
            session.multi_trader_tokens.clear()
            session.previous_messages.clear()
            session.token_pump_types.clear()
            session.token_market_caps.clear()
            session.token_sol_amounts.clear()
            session.token_timestamps.clear()
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Monitoring stopped for THETRACKOORS.\nTotal running time: {final_duration:.2f} seconds"
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Monitoring is not active for THETRACKOORS."
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="No monitoring session found for THETRACKOORS."
        )

async def main():
    await initialize_telethon()  # Start the Telethon client

    # Initialize Application instance for polling mode
    application = Application.builder().token(BOT_TOKEN).build()

    # Add command handlers for polling mode
    application.add_handler(CommandHandler("start", start))
    
    logging.info("Starting bot with polling...")

    # Start polling for updates instead of using webhooks
    await application.initialize()  # Initialize the application before running polling
    application.run_polling(drop_pending_updates=True)  # Start polling

def run_bot():
    """Runner function for the bot"""
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    try:
        asyncio.run(main())  # Run the main async function
        
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
        
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        raise

if __name__ == "__main__":
    run_bot()