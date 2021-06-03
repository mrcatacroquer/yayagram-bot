#!/usr/bin/env python
# coding=utf-8

from telegram import Update, ForceReply
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from configparser import ConfigParser
from Adafruit_Thermal import *
from datetime import datetime
from multiprocessing import Process
import base64, sys
import logging
import textwrap
import threading
import time
import RPi.GPIO as GPIO
import shlex
import uuid
import subprocess
import signal
import os
import os.path

TOKEN = "1708199126:AAFF4IBIChtx4VxpozDath35G8X4ADC5KTQ"
STOP_TG = False
STATUS = False

CONFIG_FILE = 'yayagram.conf'
CONFIG = ConfigParser()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

logger = logging.getLogger(__name__)

def start_command(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    update.message.reply_markdown_v2(
        fr'Hi {user.mention_markdown_v2()}\!',
        reply_markup=ForceReply(selective=True),
    )

def end_command(update: Update, context: CallbackContext) -> None:
    global STOP_TG
    STOP_TG = True

def help_command(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /help is issued."""
    update.message.reply_text('Help!!!')

def printboard_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Users at the Yayagram board:")
    for x in range(int(CONFIG['destinations']['DST_MAX'])):
        if not CONFIG.has_option('destinations', 'DST' + str(x) + '_TGID'):
            continue

        message = '''# {name}\nBoard position: {position}.\nTelegram ID: {tgid}.\nRaspPi PIN: {pin}.'''.format(
            name=CONFIG['destinations']['DST' + str(x) + '_NAME'],
            position=CONFIG['destinations']['DST' + str(x) + '_BOARD_POSITION'],
            tgid=CONFIG['destinations']['DST' + str(x) + '_TGID'],
            pin=CONFIG['destinations']['DST' + str(x) + '_PIN'])

        update.message.reply_text(message)

def addmeasroot_command(update: Update, context: CallbackContext) -> None:
    if CONFIG.has_option('admin', 'ADMIN_ID'):
        update.message.reply_text("Sorry, this Yayagram already has an owner")
        context.bot.send_message(chat_id=CONFIG['admin']['ADMIN_ID'],
            text="The user " + update.effective_user.full_name + "(" +
            str(update.effective_chat.id) + ") is trying to become admin.")
        return

    CONFIG.set('admin', 'ADMIN_ID', str(update.effective_chat.id))
    save_config()
    update.message.reply_text("Added! You are now the Yayagram owner")

def addme_command(update: Update, context: CallbackContext) -> None:
    pos = -1

    update.message.reply_text("Adding user to first available position...")
    for x in range(int(CONFIG['destinations']['DST_MAX'])):
        if CONFIG.has_option('destinations', 'DST' + str(x) + '_TGID'):
            if CONFIG['destinations']['DST' + str(x) + '_TGID'] != str(update.effective_chat.id):
                continue

            update.message.reply_text("You are already added to the board")
            return

        pos=x
        update.message.reply_text("Spot found at " + str(pos) + ", adding now...")
        break

    if pos == -1:
        update.message.reply_text("Cannot find spot for user.")
        return

    try:
        CONFIG.set('destinations', 'DST' + str(pos) + '_TGID', str(update.effective_chat.id))
        CONFIG.set('destinations', 'DST' + str(pos) + '_NAME', update.effective_user.full_name)
        CONFIG.set('destinations', 'DST' + str(pos) + '_BOARD_POSITION', str(pos))

        save_config()

        update.message.reply_text("Added! Your board position is: " + str(pos))
    except Exception as e:
        print_exception(e)

def removeme_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Going to remove you")
    removed = False
    for x in range(int(CONFIG['destinations']['DST_MAX'])):
        if not CONFIG.has_option('destinations', 'DST' + str(x) + '_TGID'):
            continue

        if not CONFIG['destinations']['DST' + str(x) + '_TGID'] == str(update.effective_chat.id):
            continue

        try:
            update.message.reply_text("Removing your user from the Yayagram board...")
            CONFIG.remove_option('destinations', 'DST' + str(x) + '_TGID')
            CONFIG.remove_option('destinations', 'DST' + str(x) + '_NAME')
            CONFIG.remove_option('destinations', 'DST' + str(x) + '_BOARD_POSITION')
            update.message.reply_text("Almost done. Saving removal...")
            save_config()
            update.message.reply_text("Removed!")
            removed = True
        except Exception as e:
            print_exception(e)

    if not removed:
        update.message.reply_text("Can't find you at the board")

def lockedits_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Locking the Yayagram board")
    if not is_user_admin(update, context):
        return

    CONFIG.set('admin', 'ADMIN_LOCK', 'True')
    save_config()
    update.message.reply_text("Done.")

def unlockedits_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Unlocking the Yayagram board")
    if not is_user_admin(sender,msg):
        return

    CONFIG.set('admin', 'ADMIN_LOCK', 'False')
    save_config()
    update.message.reply_text("Done.")

def is_user_admin(update: Update, context: CallbackContext):
    if update.effective_chat.id != CONFIG['admin']['ADMIN_ID']:
        reply = u"You are not my Admin.\nMy Admin has id {admin_id} but you have {user_id}".format(
            admin_id=CONFIG['admin']['ADMIN_ID'], user_id=update.effective_chat.id)
        update.message.reply_text(reply)
        return False

    return True

def echo(update: Update, context: CallbackContext) -> None:
    """Echo the user message."""
    textbody = "chatid:" + str(update.effective_chat.id)
    update.message.reply_text(update.message.text)
    context.bot.send_message(chat_id=update.effective_chat.id, text="I'm a bot, please talk to me!")
    #sei_chat_id = 1766564359
    manu_chat_id = 6941591
    #context.bot.send_message(chat_id=sei_chat_id, text="Hola Sei, desde manu")
    context.bot.send_message(chat_id=manu_chat_id, text="Hola Manu, desde manu, mandando wav")
    message = context.bot.send_document(chat_id=manu_chat_id, document=open('opusfile.opus', 'rb'))

def send_recording(updater, destination, filetosend):
    if (os.path.isfile(filetosend) == False):
        updater.bot.send_message(chat_id=destination, text=CONFIG['recording']['RECORDING_SEND_ERROR_MSG'])
        return

    if (destination == int(CONFIG['destinations']['ALL_PIN'])):
        send_broadcast(updater, filetosend)
        return

    updater.bot.send_message(chat_id=destination, text=CONFIG['global']['NEW_MSG_FOR_YOU'])
    updater.bot.send_document(chat_id=destination, document=open(filetosend, 'rb'))

def send_broadcast(updater, filetosend):
    print("Send broadcast")
    for x in range(int(CONFIG['destinations']['DST_MAX'])):
        print (str(x))
        if not CONFIG.has_option('destinations', 'DST' + str(x) + '_TGID'):
            continue

        destination_user_id = CONFIG['destinations']['DST' + str(x) + '_TGID']
        message = CONFIG['global']['BROADCAST_MESSAGE']

        updater.bot.send_message(chat_id=destination_user_id, text=message)
        updater.bot.send_document(chat_id=destination_user_id,  document=open(filetosend, 'rb'))

def do_recording():
    GPIO.output(int(CONFIG['recording']['RECORDING_LED_PIN']),GPIO.HIGH)
    fileName = CONFIG['recording']['RECORDINGS_PATH'] + str(uuid.uuid4()) + ".wav"
    command = CONFIG['recording']['ARECORD_PATH'] + " -D plughw:" + CONFIG['recording']['PLUG_HW'] + " --format=S16_LE --rate=16000 --file-type=wav " + fileName
    popen_cmd = shlex.split(command)
    pro = subprocess.Popen(popen_cmd, stdout=subprocess.PIPE, shell=False, preexec_fn=os.setsid)

    while (GPIO.input(int(CONFIG['recording']['RECORD_BUTTON_PIN']))):
        time.sleep(0.30)

    os.killpg(os.getpgid(pro.pid), signal.SIGTERM)

    GPIO.output(int(CONFIG['recording']['RECORDING_LED_PIN']),GPIO.LOW)

    time.sleep(0.30)

    return fileName

def get_yayagram_destination():
    for x in range(int(CONFIG['destinations']['DST_MAX'])):
        if not CONFIG.has_option('destinations', 'DST' + str(x) + '_TGID'):
            continue
        if not (GPIO.input(int(CONFIG['destinations']['DST' + str(x) + '_PIN']))):
            continue

        print("The " + CONFIG['destinations']['DST' + str(x) + '_NAME'] +" switch is ON")
        return CONFIG['destinations']['DST' + str(x) + '_TGID']

    if (GPIO.input(int(CONFIG['destinations']['ALL_PIN']))):
        print("The ALL_PIN input is ON")
        return int(CONFIG['destinations']['ALL_PIN'])

def load_config() -> None:
    CONFIG.read(CONFIG_FILE)

    if not CONFIG.has_section('destinations'):
            CONFIG.add_section('destinations')
    if not CONFIG.has_section('admin'):
            CONFIG.add_section('admin')
    if not CONFIG.has_section('recording'):
            CONFIG.add_section('recording')
    if not CONFIG.has_section('printer'):
            CONFIG.add_section('printer')
    if not CONFIG.has_section('global'):
            CONFIG.add_section('global')

    #Printer default parameters
    if not CONFIG.has_option('printer', 'BAUDRATE'):
        CONFIG.set('printer', 'BAUDRATE', '9600')
    if not CONFIG.has_option('printer', 'ADDR'):
        CONFIG.set('printer', 'ADDR', '/dev/serial0')
    #Record default parameters
    if not CONFIG.has_option('recording', 'RECORDINGS_PATH'):
        CONFIG.set('recording', 'RECORDINGS_PATH', '/home/pi/.telegram-cli/uploads/')
    if not CONFIG.has_option('recording', 'RECORD_BUTTON_PIN'):
        CONFIG.set('recording', 'RECORD_BUTTON_PIN', '10')
    if not CONFIG.has_option('recording', 'RECORDING_LED_PIN'):
        CONFIG.set('recording', 'RECORDING_LED_PIN', '26')
    if not CONFIG.has_option('recording', 'ARECORD_PATH'):
        CONFIG.set('recording', 'ARECORD_PATH', '/usr/bin/arecord')
    if not CONFIG.has_option('recording', 'PLUG_HW'):
        CONFIG.set('recording', 'PLUG_HW', '1,0')
    if not CONFIG.has_option('recording', 'RECORDING_SEND_ERROR_MSG'):
        CONFIG.set('recording', 'RECORDING_SEND_ERROR_MSG', 'An error occured while sending the voice message.')
    #Destinations default CONFIG
    if not CONFIG.has_option('destinations', 'DST_MAX'):
        CONFIG.set('destinations', 'DST_MAX', '2')

    if not CONFIG.has_option('destinations', 'DST0_PIN'):
        CONFIG.set('destinations', 'DST0_PIN', '6')

    if not CONFIG.has_option('destinations', 'DST1_PIN'):
        CONFIG.set('destinations', 'DST1_PIN', '5')

    if not CONFIG.has_option('destinations', 'ALL_PIN'):
        CONFIG.set('destinations', 'ALL_PIN', '13')
    #Admin default CONFIG
    if not CONFIG.has_option('admin', 'COMMAND_PREFIX'):
        CONFIG.set('admin', 'COMMAND_PREFIX', '<!>')
    if not CONFIG.has_option('admin', 'ADMIN_LOCK'):
        CONFIG.set('admin', 'ADMIN_LOCK', 'False')
    #Global default CONFIG
    if not CONFIG.has_option('global', 'BROADCAST_MESSAGE'):
        CONFIG.set('global', 'BROADCAST_MESSAGE', 'Yayagram tiene un mensaje para todos las nietas y nietos!!')
    if not CONFIG.has_option('global', 'STATUS_LED_PIN'):
        CONFIG.set('global', 'STATUS_LED_PIN', '21')
    if not CONFIG.has_option('global', 'NEW_MSG_FOR_YOU'):
        CONFIG.set('global', 'NEW_MSG_FOR_YOU', 'Yayagram tiene un mensaje para ti!!')
    if not CONFIG.has_option('global', 'THANK_YOU_FOR_MSG'):
        CONFIG.set('global', 'THANK_YOU_FOR_MSG', 'Thank you, your message has been printed :)')
    if not CONFIG.has_option('global', 'YAYAGRAM_LOCKED'):
        CONFIG.set('global', 'YAYAGRAM_LOCKED', 'This Yayagram configuration is locked.')
    if not CONFIG.has_option('global', 'TG_CLI_PATH'):
        CONFIG.set('global', 'TG_CLI_PATH', '/home/pi/tg/bin/telegram-cli')
    if not CONFIG.has_option('global', 'TG_PUB_PATH'):
        CONFIG.set('global', 'TG_PUB_PATH', '/home/pi/tg/tg-server.pub')

    save_config()

def save_config() -> None:
    with open(CONFIG_FILE, 'w') as configfile:
        CONFIG.write(configfile)

def setup_pins() -> None:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    for x in range(int(CONFIG['destinations']['DST_MAX'])):
        GPIO.setup(
            int(CONFIG['destinations']['DST' + str(x) + '_PIN']),
            GPIO.IN,
            pull_up_down = GPIO.PUD_DOWN)

    GPIO.setup(int(CONFIG['destinations']['ALL_PIN']), GPIO.IN, pull_up_down = GPIO.PUD_DOWN)
    GPIO.setup(int(CONFIG['recording']['RECORD_BUTTON_PIN']), GPIO.IN, pull_up_down = GPIO.PUD_DOWN)
    GPIO.setup(int(CONFIG['global']['STATUS_LED_PIN']), GPIO.OUT)
    GPIO.setup(int(CONFIG['recording']['RECORDING_LED_PIN']), GPIO.OUT)
    GPIO.output(int(CONFIG['global']['STATUS_LED_PIN']),GPIO.HIGH)
    GPIO.output(int(CONFIG['recording']['RECORDING_LED_PIN']),GPIO.LOW)

def status_worker() -> None:
    global STOP_TG
    global STATUS
    while not STOP_TG:
        GPIO.output(int(CONFIG['global']['STATUS_LED_PIN']),GPIO.HIGH)
        time.sleep(1)
        if (STATUS):
            GPIO.output(int(CONFIG['global']['STATUS_LED_PIN']),GPIO.LOW)
        time.sleep(1)

def sender_worker(updater) -> None:
    while not STOP_TG:
        if (GPIO.input(int(CONFIG['recording']['RECORD_BUTTON_PIN'])) == 0):
            time.sleep(0.30)
            continue

        try:
            destination = get_yayagram_destination()
            filename=do_recording()
            send_recording(updater, destination, filename)
            os.remove(filename)
        except Exception as e:
            print_exception(e)
            GPIO.output(int(CONFIG['recording']['RECORDING_LED_PIN']),GPIO.LOW)

def print_exception(e) -> None:
    if hasattr(e, 'message'):
        print("Exception sending message" + e.message)
    else:
        print("Exception sending message" + str(e))

def main() -> None:
    global STOP_TG

    print("Loading config")
    load_config()

    print ("Doing pins setup")
    setup_pins()

    print("Creating Status thread")
    status_thread = threading.Thread(target=status_worker)
    status_thread.setName("TheStatusThread")
    status_thread.daemon = True
    status_thread.start()

    print ("Start the bot")

    updater = Updater(TOKEN)

    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start_command))
    dispatcher.add_handler(CommandHandler("end", end_command))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("printboard", printboard_command))
    dispatcher.add_handler(CommandHandler("lockedits", lockedits_command))
    dispatcher.add_handler(CommandHandler("unlockedits", unlockedits_command))
    dispatcher.add_handler(CommandHandler("addmeasroot", addmeasroot_command))
    dispatcher.add_handler(CommandHandler("addme", addme_command))
    dispatcher.add_handler(CommandHandler("removeme", removeme_command))

    message_handler = MessageHandler(Filters.text & ~Filters.command, echo)
    dispatcher.add_handler(message_handler)

    print("Creating Sender thread")
    sender_thread = threading.Thread(target=sender_worker, args=(updater,))
    sender_thread.setName("TheSenderThread")
    sender_thread.daemon = True
    sender_thread.start()

    print("Start polliing")
    updater.start_polling()

    if CONFIG.has_option('admin', 'ADMIN_ID'):
        updater.bot.send_message(int(CONFIG['admin']['ADMIN_ID']), text="Yayagram up!")
    STATUS = True

    updater.idle()

    STOP_TG = True

    print("Waiting for sender thread")
    sender_thread.join()
    print("Waiting for status thread")
    status_thread.join()
    GPIO.output(int(CONFIG['global']['STATUS_LED_PIN']),GPIO.LOW)

    print("Bye")

if __name__ == '__main__':
    main()
