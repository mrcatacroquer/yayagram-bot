#!/usr/bin/env python
# coding=utf-8

from telegram import Update, ForceReply, BotCommand
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from configparser import ConfigParser
from Adafruit_Thermal import *
from datetime import datetime, timedelta
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
import requests
import filecmp
import socket
import zipfile

STOP_TG = False
STATUS = False

CONFIG_FILE = 'yayagram.conf'
CONFIG = ConfigParser()
UPDATER = None

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

LOGGER = logging.getLogger(__name__)

def process_yayagram_message_command(update: Update, context: CallbackContext) -> None:
    LOGGER.info("Printing message from " + str(update.effective_user.full_name))
    nickname = get_nickname(str(update.effective_chat.id), str(update.effective_user.full_name))

    PRINTER = Adafruit_Thermal(
        CONFIG['printer']['ADDR'],
        CONFIG['printer']['BAUDRATE'],
        timeout=5)

    PRINTER.reset()
    PRINTER.flush()

    PRINTER.setSize('S')
    PRINTER.println("--------------------------------")
    PRINTER.println("")
    PRINTER.setSize('L')
    PRINTER.println(CONFIG['global']['MSG_FROM'] + nickname + ":")

    lines = update.message.text.split("\n")
    lists = (textwrap.TextWrapper(width=32,break_long_words=False).wrap(line) for line in lines)
    messageToPrint  = "\n".join("\n".join(list) for list in lists)

    PRINTER.setSize('M')
    PRINTER.println()
    PRINTER.println(clean_str(messageToPrint))
    PRINTER.setSize('S')
    PRINTER.println("--------------------------------")
    PRINTER.println(str(update.message.date + timedelta(hours=int(CONFIG['global']['TIME_OFFSET']))))
    PRINTER.setDefault()
    PRINTER.feed(2)

    update.message.reply_text(CONFIG['global']['THANK_YOU_FOR_MSG'])

def end_command(update: Update, context: CallbackContext) -> None:
    global STOP_TG
    STOP_TG = True

def printpins_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Pins at the Yayagram board:")

    message = ''
    for x in range(int(CONFIG['destinations']['DST_MAX'])):
        if not CONFIG.has_option('destinations', 'DST' + str(x) + '_TGID'):
            continue

        user_alias = '-'
        if CONFIG.has_option('destinations', 'DST' + str(x) + '_NICKNAME'):
            user_alias = CONFIG['destinations']['DST' + str(x) + '_NICKNAME']

        message = message + '''# PIN: {pin}\n\tName: {name}\n\tNickname: {nickname}\n\tBoard position: {position}.\n'''.format(
            name=CONFIG['destinations']['DST' + str(x) + '_NAME'],
            nickname=user_alias,
            position=CONFIG['destinations']['DST' + str(x) + '_BOARD_POSITION'],
            pin=CONFIG['destinations']['DST' + str(x) + '_PIN'])

    message = message + '''# ALL_PIN: {allpin}.\n'''.format(
        allpin=CONFIG['destinations']['ALL_PIN'])

    message = message + '''# RECORD_BUTTON_PIN: {recordpin}.\n'''.format(
        recordpin=CONFIG['recording']['RECORD_BUTTON_PIN'])

    message = message + '''# STATUS_LED_PIN: {statuspin}.\n'''.format(
        statuspin=CONFIG['global']['STATUS_LED_PIN'])

    message = message + '''# RECORDING_LED_PIN: {recordingledpin}.\n'''.format(
        recordingledpin=CONFIG['recording']['RECORDING_LED_PIN'])

    update.message.reply_text(message)

def printboard_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Users at the Yayagram board:")
    for x in range(int(CONFIG['destinations']['DST_MAX'])):
        if not CONFIG.has_option('destinations', 'DST' + str(x) + '_TGID'):
            continue

        user_alias = '-'
        if CONFIG.has_option('destinations', 'DST' + str(x) + '_NICKNAME'):
            user_alias = CONFIG['destinations']['DST' + str(x) + '_NICKNAME']

        message = '''# {name}\nNickname: {nickname}.\nBoard position: {position}.\nTelegram ID: {tgid}.\nRaspPi PIN: {pin}.'''.format(
            name=CONFIG['destinations']['DST' + str(x) + '_NAME'],
            nickname=user_alias,
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

    LOGGER.info("Root user added:" + str(update.effective_chat.id))

    CONFIG.set('admin', 'ADMIN_ID', str(update.effective_chat.id))
    save_config()
    update.message.reply_text("Added! You are now the Yayagram owner")

def settimeoffset_command(update: Update, context: CallbackContext) -> None:
    if read_only_yayagram():
        update.message.reply_text(CONFIG['global']['YAYAGRAM_LOCKED'])
        return

    offset=update.message.text.replace('/settimeoffset ', '')
    update.message.reply_text("Setting '" + offset + "' as the new time offset")
    CONFIG.set('global', 'TIME_OFFSET', offset)
    save_config()
    update.message.reply_text("Done!")

def get_user_position(user_id):
    for x in range(int(CONFIG['destinations']['DST_MAX'])):
        if CONFIG.has_option('destinations', 'DST' + str(x) + '_TGID'):
            if CONFIG['destinations']['DST' + str(x) + '_TGID'] != user_id:
                continue

            return x

    return -1

def get_nickname(user_id, efective_full_name):
    pos = get_user_position(user_id)

    if pos == -1:
        return efective_full_name

    if not CONFIG.has_option('destinations', 'DST' + str(pos) + '_NICKNAME'):
        return efective_full_name

    return CONFIG['destinations']['DST' + str(pos) + '_NICKNAME']

def add_nickname_command(update: Update, context: CallbackContext) -> None:
    if read_only_yayagram():
        update.message.reply_text(CONFIG['global']['YAYAGRAM_LOCKED'])
        return

    nickname = update.message.text.replace('/addmynickname ', '')
    if not nickname:
        update.message.reply_text(CONFIG['global']['NO_NICKNAME_GIVEN'])
        return

    pos = get_user_position(str(update.effective_chat.id))

    update.message.reply_text("Adding your new nickname...")
    CONFIG.set('destinations', 'DST' + str(pos) + '_NICKNAME', nickname)
    save_config()
    update.message.reply_text(CONFIG['global']['NICKNAME_ADDED'] + nickname)

def addme_command(update: Update, context: CallbackContext) -> None:
    if read_only_yayagram():
        update.message.reply_text(CONFIG['global']['YAYAGRAM_LOCKED'])
        return

    pos = -1
    bulkaddme=update.message.text.replace('/addme', '')
    update.message.reply_text("Adding user to first available position...")
    for x in range(int(CONFIG['destinations']['DST_MAX'])):
        if CONFIG.has_option('destinations', 'DST' + str(x) + '_TGID'):
            if CONFIG['destinations']['DST' + str(x) + '_TGID'] != str(update.effective_chat.id):
                continue

            if not bulkaddme:
                update.message.reply_text("You are already added to the board")
                return

        pos=x
        update.message.reply_text("Spot found at " + str(pos) + ", adding now...")
        add_user_to_board(update, str(update.effective_chat.id), update.effective_user.full_name, str(pos))

        if not bulkaddme:
            return

    if pos != -1:
        return

    update.message.reply_text("Cannot find spot for user.")

def add_user_to_board(update, id, full_name, pos) -> None:
    try:
        CONFIG.set('destinations', 'DST' + str(pos) + '_TGID', id)
        CONFIG.set('destinations', 'DST' + str(pos) + '_NAME', full_name)
        CONFIG.set('destinations', 'DST' + str(pos) + '_BOARD_POSITION', pos)

        save_config()

        update.message.reply_text("Added! Your board position is: " + str(pos))

        LOGGER.info("User added: " + full_name)
    except Exception as e:
        print_exception(e)
        os._exit(1)

def removeme_command(update: Update, context: CallbackContext) -> None:
    if read_only_yayagram():
        update.message.reply_text(CONFIG['global']['YAYAGRAM_LOCKED'])
        return

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
            CONFIG.remove_option('destinations', 'DST' + str(x) + '_NICKNAME')
            CONFIG.remove_option('destinations', 'DST' + str(x) + '_BOARD_POSITION')
            update.message.reply_text("Almost done. Saving removal...")
            save_config()
            update.message.reply_text("Removed!")
            removed = True

            LOGGER.info("User removed: " + update.effective_user.full_name)
        except Exception as e:
            print_exception(e)
            os._exit(1)

    if not removed:
        update.message.reply_text("Can't find you at the board")

def lockedits_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Locking the Yayagram board")
    if not is_user_admin(update, context):
        return

    CONFIG.set('admin', 'ADMIN_LOCK', 'True')
    save_config()
    update.message.reply_text("Done.")

    LOGGER.info("Yayagram locked for edits")

def unlockedits_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Unlocking the Yayagram board")
    if not is_user_admin(update, context):
        return

    CONFIG.set('admin', 'ADMIN_LOCK', 'False')
    save_config()
    update.message.reply_text("Done.")

    LOGGER.info("Yayagram un-locked for edits")

def upgrade_command(update: Update, context: CallbackContext) -> None:
    LOGGER.info("Starting Yayagram upgrade")
    update.message.reply_text("Going to upgrade the Yayagram")
    if not is_user_admin(update, context):
        return

    url = 'http://www.yayagram.xyz/yayafiles/index.php/s/u1ttz1U086bjGJ9/download'
    r = requests.get(url, allow_redirects=True)
    open('yayagram-bot-new.zip', 'wb').write(r.content)

    update.message.reply_text("Latest version downloaded")

    if (os.path.isfile('yayagram-bot-current.zip') and filecmp.cmp('yayagram-bot-new.zip', 'yayagram-bot-current.zip', shallow=False)):
        update.message.reply_text("This Yayagram already has the newer version")
        os.remove('yayagram-bot-new.zip')
        return

    with zipfile.ZipFile('yayagram-bot-new.zip', 'r') as zip_ref:
        zip_ref.extractall('.')

    if os.path.isfile('yayagram-bot-current.zip'):
        os.remove('yayagram-bot-current.zip')
    os.rename('yayagram-bot-new.zip', 'yayagram-bot-current.zip')

    update.message.reply_text("Upgrade completed, restarting the Yayagram.")
    LOGGER.info("Upgrade: New version deployed")

    os._exit(1)

def printip_command(update: Update, context: CallbackContext):
    host_name = socket.gethostname()
    update.message.reply_text("Hostname: " + str(host_name))
    host_addr = socket.gethostbyname(host_name + ".local")
    update.message.reply_text("Private IP:" + str(host_addr))

def is_user_admin(update: Update, context: CallbackContext):
    if str(update.effective_chat.id) != str(CONFIG['admin']['ADMIN_ID']):
        reply = u"You are not my Admin.\nMy Admin has id {admin_id} but you have {user_id}".format(
            admin_id=CONFIG['admin']['ADMIN_ID'], user_id=update.effective_chat.id)
        update.message.reply_text(reply)
        return False

    return True

def send_recording(destination, filetosend):
    if (os.path.isfile(filetosend) == False):
        UPDATER.bot.send_message(chat_id=destination, text=CONFIG['recording']['RECORDING_SEND_ERROR_MSG'])
        return

    if (destination == int(CONFIG['destinations']['ALL_PIN'])):
        send_broadcast(filetosend)
        return

    UPDATER.bot.send_message(chat_id=destination, text=CONFIG['global']['NEW_MSG_FOR_YOU'])
    UPDATER.bot.send_document(chat_id=destination, document=open(filetosend, 'rb'))

    LOGGER.info("Message voice sent to:" + str(destination))

def send_broadcast(filetosend):
    LOGGER.info("Sending broadcast message")
    for x in range(int(CONFIG['destinations']['DST_MAX'])):
        if not CONFIG.has_option('destinations', 'DST' + str(x) + '_TGID'):
            continue

        destination_user_id = CONFIG['destinations']['DST' + str(x) + '_TGID']
        message = CONFIG['global']['BROADCAST_MESSAGE']

        UPDATER.bot.send_message(chat_id=destination_user_id, text=message)
        UPDATER.bot.send_document(chat_id=destination_user_id,  document=open(filetosend, 'rb'))

    LOGGER.info("Sending broadcast message done")

def do_recording():
    print("Doing a recording")

    GPIO.output(int(CONFIG['recording']['RECORDING_LED_PIN']),GPIO.HIGH)
    fileName = CONFIG['recording']['RECORDINGS_PATH'] + str(uuid.uuid4()) + ".opus"
    arecord_command_raw = CONFIG['recording']['ARECORD_PATH'] + " -D plughw:" + CONFIG['recording']['PLUG_HW'] + " -r 48000 -f S16_LE -t raw "
    opu_command_raw = "opusenc --raw-chan 1 --bitrate 48 - " + fileName

    arecord_cmd = shlex.split(arecord_command_raw)
    opu_cmd = shlex.split(opu_command_raw)


    arecord_sub_p = subprocess.Popen(arecord_cmd, stdout=subprocess.PIPE,shell=False, preexec_fn=os.setsid)
    grep = subprocess.Popen(opu_cmd, stdin=arecord_sub_p.stdout, stdout=subprocess.PIPE,shell=False)

    while (GPIO.input(int(CONFIG['recording']['RECORD_BUTTON_PIN']))):
        time.sleep(0.30)

    os.killpg(os.getpgid(arecord_sub_p.pid), signal.SIGTERM)

    GPIO.output(int(CONFIG['recording']['RECORDING_LED_PIN']),GPIO.LOW)

    time.sleep(0.30)

    return fileName

def get_yayagram_destination():
    for x in range(int(CONFIG['destinations']['DST_MAX'])):
        if not CONFIG.has_option('destinations', 'DST' + str(x) + '_TGID'):
            continue
        if not (GPIO.input(int(CONFIG['destinations']['DST' + str(x) + '_PIN']))):
            continue

        LOGGER.info("The " + CONFIG['destinations']['DST' + str(x) + '_NAME'] +" switch is ON")

        print("Destination: " + str(CONFIG['destinations']['DST' + str(x) + '_TGID']))
        return CONFIG['destinations']['DST' + str(x) + '_TGID']

    if (GPIO.input(int(CONFIG['destinations']['ALL_PIN']))):
        print("Doing a broadcast")
        LOGGER.info("The ALL_PIN input is ON")
        return int(CONFIG['destinations']['ALL_PIN'])

def addBotCommands():
    addmecommand = BotCommand('addme','Añade tu usuario al Yayagram')
    removemecommand = BotCommand('removeme','Elimina tu usuario del Yayagram')
    printboardcommand = BotCommand('printboard','Imprime la lista de usuarios del Yayagram')
    printpinscommand = BotCommand('printpins','Imprime los pins utilizados para los contactos')
    settimeoffsetcommand = BotCommand('settimeoffset','Establece en incremento a UCT')
    addmeasrootcommand = BotCommand('addmeasroot','Añade el usuario como administrador')
    lockeditscommand = BotCommand('lockedits','Bloquea modificaciones en el Yayagram')
    unlockeditscommand = BotCommand('unlockedits','Desbloquea el Yayagram para cambios')
    upgradecommand = BotCommand('upgrade','Actualiza el software del Yayagram')
    endcommand = BotCommand('end','Detiene la ejecución del Yayagram')
    printipcommand = BotCommand('printip','Imprime la IP privada del Yayagram')
    addmynicknamecommand = BotCommand('addmynickname','Añade un alias para tu usuario')

    UPDATER.bot.set_my_commands([addmecommand,removemecommand,printboardcommand,
        printpinscommand,endcommand,settimeoffsetcommand,addmeasrootcommand,
        lockeditscommand, unlockeditscommand, upgradecommand, printipcommand,
        addmynicknamecommand])

def registerBotCommands():
    UPDATER.dispatcher.add_handler(CommandHandler("printboard", printboard_command))
    UPDATER.dispatcher.add_handler(CommandHandler("printpins", printpins_command))
    UPDATER.dispatcher.add_handler(CommandHandler("lockedits", lockedits_command))
    UPDATER.dispatcher.add_handler(CommandHandler("unlockedits", unlockedits_command))
    UPDATER.dispatcher.add_handler(CommandHandler("addmeasroot", addmeasroot_command))
    UPDATER.dispatcher.add_handler(CommandHandler("addme", addme_command))
    UPDATER.dispatcher.add_handler(CommandHandler("removeme", removeme_command))
    UPDATER.dispatcher.add_handler(CommandHandler("settimeoffset", settimeoffset_command))
    UPDATER.dispatcher.add_handler(CommandHandler("upgrade", upgrade_command))
    UPDATER.dispatcher.add_handler(CommandHandler("printip", printip_command))
    UPDATER.dispatcher.add_handler(CommandHandler("addmynickname", add_nickname_command))

    message_handler = MessageHandler(Filters.text & ~Filters.command, process_yayagram_message_command)
    UPDATER.dispatcher.add_handler(message_handler)

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
    if not CONFIG.has_option('admin', 'token'):
        CONFIG.set('admin', 'token', '')
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
    if not CONFIG.has_option('global', 'NO_NICKNAME_GIVEN'):
        CONFIG.set('global', 'NO_NICKNAME_GIVEN', 'You have to provide a nickname, please retry.')
    if not CONFIG.has_option('global', 'NICKNAME_ADDED'):
        CONFIG.set('global', 'NICKNAME_ADDED', 'Done! Your nickname now is: ')
    if not CONFIG.has_option('global', 'MSG_FROM'):
        CONFIG.set('global', 'MSG_FROM', 'From ')
    if not CONFIG.has_option('global', 'TIME_OFFSET'):
        CONFIG.set('global', 'TIME_OFFSET', '2')

    save_config()

def save_config() -> None:
    with open(CONFIG_FILE, 'w') as configfile:
        CONFIG.write(configfile)

def read_only_yayagram():
    if not CONFIG.has_option('admin', 'ADMIN_LOCK'):
        return False

    return CONFIG['admin']['ADMIN_LOCK'] == 'True'

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
    while not STOP_TG:
        GPIO.output(int(CONFIG['global']['STATUS_LED_PIN']),GPIO.HIGH)
        time.sleep(1)
        if (STATUS):
            GPIO.output(int(CONFIG['global']['STATUS_LED_PIN']),GPIO.LOW)

        time.sleep(1)

def check_connection_worker() -> None:
    global STATUS
    while not STOP_TG:
        if not is_connected_to_inet():
            STATUS=False
        else:
            STATUS=True

        time.sleep(5)

def is_connected_to_inet():
    try:
        host = socket.gethostbyname("one.one.one.one")
        s = socket.create_connection((host, 80), 2)
        s.close()
        return True
    except:
        pass

    return False

def sender_worker() -> None:
    global STOP_TG
    while not STOP_TG:
        if (GPIO.input(int(CONFIG['recording']['RECORD_BUTTON_PIN'])) == 0):
            time.sleep(0.30)
            continue

        try:
            destination = get_yayagram_destination()
            filename=do_recording()
            send_recording(destination, filename)
            os.remove(filename)
        except Exception as e:
            print_exception(e)
            GPIO.output(int(CONFIG['recording']['RECORDING_LED_PIN']),GPIO.LOW)
            os._exit(1)

def clean_str(message):
    message = message.replace('á' , 'a')
    message = message.replace('Á' , 'A')
    message = message.replace('é' , 'e')
    message = message.replace('É' , 'E')
    message = message.replace('í' , 'i')
    message = message.replace('Í' , 'I')
    message = message.replace('ó' , 'o')
    message = message.replace('Ó' , 'O')
    message = message.replace('ú' , 'u')
    message = message.replace('Ú' , 'U')
    message = message.replace('ñ' , 'n')
    message = message.replace('Ñ' , 'N')
    message = message.replace('ü' , 'u')
    message = message.replace('Ü' , 'U')

    return message

def print_exception(e) -> None:
    if hasattr(e, 'message'):
        LOGGER.fatal("Exception: " + e.message)
    else:
        LOGGER.fatal("Exception: " + str(e))

def main() -> None:
    global STOP_TG
    global UPDATER

    LOGGER.info("Loading config")
    load_config()

    LOGGER.info("Doing pins setup")
    setup_pins()

    if not os.path.isdir(CONFIG['recording']['RECORDINGS_PATH']):
        os.makedirs(CONFIG['recording']['RECORDINGS_PATH'])

    LOGGER.info("Creating Status thread")
    status_thread = threading.Thread(target=status_worker)
    status_thread.setName("TheStatusThread")
    status_thread.daemon = True
    status_thread.start()

    LOGGER.info("Starting the bot")
    UPDATER = Updater(CONFIG['admin']['token'])

    LOGGER.info("Adding commands to bot")
    addBotCommands()

    LOGGER.info("Registering commands")
    registerBotCommands()

    LOGGER.info("Creating Sender thread")
    sender_thread = threading.Thread(target=sender_worker)
    sender_thread.setName("TheSenderThread")
    sender_thread.daemon = True
    sender_thread.start()

    LOGGER.info("Start polling")
    UPDATER.start_polling()

    if CONFIG.has_option('admin', 'ADMIN_ID'):
        UPDATER.bot.send_message(int(CONFIG['admin']['ADMIN_ID']), text="Yayagram up!")

    LOGGER.info("Creating check inet connection thread")
    cc_thread = threading.Thread(target=check_connection_worker)
    cc_thread.setName("TheCheckConnectionThread")
    cc_thread.daemon = True
    cc_thread.start()

    LOGGER.info("Going idle")
    status_thread.join()
    LOGGER.info("Status thread done.")
    sender_thread.join()
    LOGGER.info("Sender thread done.")
    cc_thread.join()
    LOGGER.info("Check connection thread done.")

    GPIO.output(int(CONFIG['global']['STATUS_LED_PIN']),GPIO.LOW)

    LOGGER.info("Stoping updater")
    UPDATER.bot.send_message(int(CONFIG['admin']['ADMIN_ID']), text="Bye my friend! It's time to leave.")
    UPDATER.stop()

    LOGGER.info("Bye")

if __name__ == '__main__':
    main()
