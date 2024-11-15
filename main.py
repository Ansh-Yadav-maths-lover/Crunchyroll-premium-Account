from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext, MessageHandler, filters
import firebase_admin
from firebase_admin import credentials, db
import random
import string
import asyncio
from telegram.error import BadRequest
import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Admin check
ADMIN_USER_ID = 5601214166
broadcast_enabled = False  # Global flag for broadcast mode

# Initialize Firebase Admin SDK
cred = credentials.Certificate("crunchyroll-premium-firebase.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://crunchyroll-premium-default-rtdb.asia-southeast1.firebasedatabase.app'
})

# Channel to check
CHANNEL_USERNAME = '@ansh_book'

# FastAPI app for health checks
app = FastAPI()

@app.get("/health")
async def health_check():
    return JSONResponse(content={"status": "ok"})

# Admin check function
def is_admin(user_id):
    return user_id == ADMIN_USER_ID

# Check if user is a member of the channel
async def is_member_of_channel(update: Update, context: CallbackContext) -> bool:
    try:
        user = update.effective_user
        chat_member = await context.bot.get_chat_member(CHANNEL_USERNAME, user.id)

        if chat_member.status in ['member', 'administrator', 'creator']:
            return True
        else:
            return False
    except BadRequest:
        return False


# Command: Start
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    user_ref = db.reference(f'users/{user.id}')

    # Check if user is already in the database
    if not user_ref.get():
        user_ref.set({'username': user.username, 'points': 0})

    # Check if user has joined the channel
    if await is_member_of_channel(update, context):
        # User is a member of the channel, proceed with the usual flow
        welcome_message = f"""
        Welcome {user.first_name}! 🎉

Here's how to get started with Crunchyroll Premium Bot:

1️⃣ **Redeem a Code**: 
    - Use /redeem <code> to redeem points and get a premium Crunchyroll account.

2️⃣ **Check Your Balance**: 
    - Use /balance to check how many points you have.

3️⃣ **Get an Account**: 
    - Use /get to redeem an account when you have enough points (Each account costs 10 points).

4️⃣ **Stay Updated**: 
    - Join our updates channel for the latest news and offers: @ansh_book ✅

            Enjoy using the bot and happy redeeming! 😄
        """
        await update.message.reply_text(welcome_message)
    else:
        # User is not a member of the channel
        await update.message.reply_text(
            "You are not a member of the channel @ansh_book. Please Join the channel to use the bot."
        )

# Command: Redeem Code
async def redeem(update: Update, context: CallbackContext):
    if not await is_member_of_channel(update, context):
        await update.message.reply_text(
            "You are no longer a member of the channel @ansh_book. Please rejoin the channel to use the bot."
        )
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /redeem <code>")
        return

    code = context.args[0]
    code_ref = db.reference(f'codes/{code}')
    code_data = code_ref.get()

    if not code_data:
        await update.message.reply_text("Invalid code!")
    elif code_data.get('used', 0) == 1:
        await update.message.reply_text("Code already used!")
    else:
        points = code_data['points']
        code_ref.update({'used': 1})

        user_ref = db.reference(f'users/{update.effective_user.id}')
        user_data = user_ref.get()
        user_ref.update({'points': user_data['points'] + points})

        await update.message.reply_text(f"Code redeemed! You got {points} points.")

# Command: Get Account
async def get_account(update: Update, context: CallbackContext):
    if not await is_member_of_channel(update, context):
        await update.message.reply_text(
            "You are no longer a member of the channel @ansh_book. Please rejoin the channel to use the bot."
        )
        return

    user_ref = db.reference(f'users/{update.effective_user.id}')
    user_data = user_ref.get()

    if not user_data or user_data['points'] < 10:
        await update.message.reply_text("Not enough points! Each account costs 10 points.")
        return

    accounts_ref = db.reference('accounts')
    accounts = accounts_ref.get()
    if not accounts:
        await update.message.reply_text("No accounts available right now!")
    else:
        account_id, account_data = next(iter(accounts.items()))
        accounts_ref.child(account_id).delete()

        user_ref.update({'points': user_data['points'] - 10})

        # Countdown before showing account credentials
        await countdown(update)

        # Send account details after countdown
        email, password = account_data['credentials'].split(":")
        message = f"""
Congratulations 🎉 you have redeemed your account.

Email: {email}
Password: {password}

Join @ansh_book ✅
"""
        await update.message.reply_text(message)

# Countdown function (3... 2... 1...)
async def countdown(update: Update):
    countdown_message = await update.message.reply_text("Processing in... 3...")
    for i in range(2, 0, -1):
        await asyncio.sleep(1)  # Pause for 1 second between countdowns
        await countdown_message.edit_text(f"Processing in... {i}...")  # Update the same message
    await asyncio.sleep(1)  # One last second before displaying the account
    await countdown_message.edit_text("Processing completed! 🎉")  # Final message after countdown

# Command: Add Code (Admin only)
async def add_code(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to add codes.")
        return

    if len(context.args) != 2:
        await update.message.reply_text("Usage: /addcode <code> <points>")
        return

    code, points = context.args
    points = int(points)  # Ensure points is an integer

    code_ref = db.reference(f'codes/{code}')
    if code_ref.get():
        await update.message.reply_text("This code already exists!")
        return

    code_ref.set({'points': points, 'used': 0})
    await update.message.reply_text(f"Code {code} added successfully!")

# Command: Add Accounts in Bulk (Admin only)
async def add_bulk_accounts(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to add accounts.")
        return

    # Expect accounts in the format: /addbulkaccounts <username1>:<password1> <username2>:<password2> ...
    accounts_data = context.args
    if not accounts_data:
        await update.message.reply_text("Usage: /addbulkaccounts <username1>:<password1> <username2>:<password2> ...")
        return

    for account in accounts_data:
        username, password = account.split(':')
        account_ref = db.reference(f'accounts/{username}')

        # Check if the account already exists
        if account_ref.get():
            await update.message.reply_text(f"Account {username} already exists!")
        else:
            # Add new account to Firebase
            account_ref.set({'credentials': f'{username}:{password}'})
            await update.message.reply_text(f"Account {username} added successfully!")

# Command: Generate Random Codes (Admin only)
async def generate_codes(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to generate codes.")
        return

    if len(context.args) != 2:
        await update.message.reply_text("Usage: /generatecodes <number_of_codes> <Amount of coins>")
        return

    num_codes = int(context.args[0])
    coin_amount = int(context.args[1])

    # Generate random codes
    generated_codes = []
    for _ in range(num_codes):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        generated_codes.append(code)

        # Save the generated code to Firebase under 'codes' with points and used flag
        code_ref = db.reference(f'codes/{code}')
        code_ref.set({'points': coin_amount, 'used': 0})

    # Format the message for code generation
    code_message = f"{num_codes} redeem code(s) generated! 🎉\n\n"
    for code in generated_codes:
        code_message += f"Code: {code} | Coins: {coin_amount}\n"
    code_message += "\n/redeem <code>\nSend ss here - @contact_ansh"

    # Send to the admin and broadcast to all users
    await update.message.reply_text(code_message)

    # Broadcast the code generation message to all users
    users_ref = db.reference('users')
    users = users_ref.get()
    if users:
        for user_id in users:
            try:
                await context.bot.send_message(user_id, code_message)
            except Exception as e:
                print(f"Error sending message to {user_id}: {e}")


# Command: Balance
async def balance(update: Update, context: CallbackContext):
    if not await is_member_of_channel(update, context):
        await update.message.reply_text(
            "You are no longer a member of the channel @ansh_book. Please rejoin the channel to use the bot."
        )
        return

    user_ref = db.reference(f'users/{update.effective_user.id}')
    user_data = user_ref.get()

    if not user_data:
        await update.message.reply_text("You don't have an account yet. Please start using the bot.")
    else:
        await update.message.reply_text(f"Your current balance is: {user_data['points']} points.")

# Command: Enable Broadcast Mode
async def enable_broadcast(update: Update, context: CallbackContext):
    global broadcast_enabled
    if is_admin(update.effective_user.id):
        broadcast_enabled = True
        await update.message.reply_text("Broadcast mode enabled! Send the message you want to broadcast to all users.")
    else:
        await update.message.reply_text("You are not authorized to use broadcast mode.")

# Command: Handle Broadcast
async def handle_broadcast(update: Update, context: CallbackContext):
    global broadcast_enabled
    if broadcast_enabled and is_admin(update.effective_user.id):
        # Send the admin message to all users
        users_ref = db.reference('users')
        users = users_ref.get()
        if users:
            for user_id in users:
                try:
                    await context.bot.send_message(user_id, update.message.text)
                except Exception as e:
                    print(f"Error sending message to {user_id}: {e}")

        # Disable broadcast mode after the message is sent
        broadcast_enabled = False
        await update.message.reply_text("Broadcast message sent to all users. Broadcast mode is now disabled.")

# Main Function
def main():
    port = int(os.getenv("PORT", 8080))  # Default to 8080 if not set

    application = Application.builder().token("YOUR_BOT_TOKEN").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("redeem", redeem))
    application.add_handler(CommandHandler("get", get_account))
    application.add_handler(CommandHandler("addcode", add_code))
    application.add_handler(CommandHandler("addbulkaccounts", add_bulk_accounts))
    application.add_handler(CommandHandler("generatecodes", generate_codes))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("broadcast", enable_broadcast))

    # Add MessageHandler with text filter for broadcast
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast))

    # Run the bot on the dynamic port
    application.run_polling(allowed_updates=Update.ALL_TYPES, port=port)

# Example route
@app.get("/")
def read_root():
    return {"Hello": "World"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

