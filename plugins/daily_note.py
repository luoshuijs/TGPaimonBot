import datetime
import os

from genshin import DataNotPublic
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import CommandHandler, MessageHandler, ConversationHandler, filters, \
    CallbackContext

from app.cookies.service import CookiesService
from app.template import TemplateService
from app.user import UserService
from app.user.repositories import UserNotFoundError
from logger import Log
from plugins.base import BasePlugins
from utils.app.inject import inject
from utils.decorators.error import error_callable
from utils.decorators.restricts import restricts
from utils.helpers import get_genshin_client
from utils.plugins.manager import listener_plugins_class


@listener_plugins_class()
class DailyNote(BasePlugins):
    """每日便签"""

    COMMAND_RESULT, = range(10200, 10201)

    @inject
    def __init__(self, user_service: UserService = None, cookies_service: CookiesService = None,
                 template_service: TemplateService = None):
        self.template_service = template_service
        self.cookies_service = cookies_service
        self.user_service = user_service
        self.current_dir = os.getcwd()

    @classmethod
    def create_handlers(cls) -> list:
        daily_note = cls()
        return [CommandHandler('dailynote', daily_note.command_start, block=True),
                MessageHandler(filters.Regex(r"^当前状态(.*)"), daily_note.command_start, block=True)]

    async def _get_daily_note(self, client) -> bytes:
        daily_info = await client.get_genshin_notes(client.uid)
        day = datetime.datetime.now().strftime("%m-%d %H:%M") + " 星期" + "一二三四五六日"[datetime.datetime.now().weekday()]
        resin_recovery_time = daily_info.resin_recovery_time.strftime("%m-%d %H:%M") if \
            daily_info.max_resin - daily_info.current_resin else None
        realm_recovery_time = (datetime.datetime.now().astimezone() +
                               daily_info.remaining_realm_currency_recovery_time).strftime("%m-%d %H:%M") if \
            daily_info.max_realm_currency - daily_info.current_realm_currency else None
        remained_time = None
        for i in daily_info.expeditions:
            if remained_time:
                if remained_time < i.remaining_time:
                    remained_time = i.remaining_time
            else:
                remained_time = i.remaining_time
        if remained_time:
            remained_time = (datetime.datetime.now().astimezone() + remained_time).strftime("%m-%d %H:%M")
        transformer, transformer_ready, transformer_recovery_time = False, None, None
        if daily_info.remaining_transformer_recovery_time is not None:
            transformer = True
            transformer_ready = daily_info.remaining_transformer_recovery_time.total_seconds() == 0
            transformer_recovery_time = daily_info.transformer_recovery_time.strftime("%m-%d %H:%M")
        daily_data = {
            "uid": client.uid,
            "day": day,
            "resin_recovery_time": resin_recovery_time,
            "current_resin": daily_info.current_resin,
            "max_resin": daily_info.max_resin,
            "realm_recovery_time": realm_recovery_time,
            "current_realm_currency": daily_info.current_realm_currency,
            "max_realm_currency": daily_info.max_realm_currency,
            "claimed_commission_reward": daily_info.claimed_commission_reward,
            "completed_commissions": daily_info.completed_commissions,
            "max_commissions": daily_info.max_commissions,
            "expeditions": bool(daily_info.expeditions),
            "remained_time": remained_time,
            "current_expeditions": len(daily_info.expeditions),
            "max_expeditions": daily_info.max_expeditions,
            "remaining_resin_discounts": daily_info.remaining_resin_discounts,
            "max_resin_discounts": daily_info.max_resin_discounts,
            "transformer": transformer,
            "transformer_ready": transformer_ready,
            "transformer_recovery_time": transformer_recovery_time
        }
        png_data = await self.template_service.render('genshin/daily_note', "daily_note.html", daily_data,
                                                      {"width": 600, "height": 548}, full_page=False)
        return png_data

    @restricts
    @error_callable
    async def command_start(self, update: Update, context: CallbackContext) -> None:
        user = update.effective_user
        message = update.message
        Log.info(f"用户 {user.full_name}[{user.id}] 查询游戏状态命令请求")
        try:
            client = await get_genshin_client(user.id, self.user_service, self.cookies_service)
            png_data = await self._get_daily_note(client)
        except UserNotFoundError:
            reply_message = await message.reply_text("未查询到账号信息，请先私聊派蒙绑定账号")
            if filters.ChatType.GROUPS.filter(message):
                self._add_delete_message_job(context, reply_message.chat_id, reply_message.message_id, 30)
                self._add_delete_message_job(context, message.chat_id, message.message_id, 30)
            return
        except DataNotPublic:
            reply_message = await update.message.reply_text("查询失败惹，可能是便签功能被禁用了？")
            if filters.ChatType.GROUPS.filter(message):
                self._add_delete_message_job(context, reply_message.chat_id, reply_message.message_id, 300)
                self._add_delete_message_job(context, message.chat_id, message.message_id, 300)
            return ConversationHandler.END
        await update.message.reply_chat_action(ChatAction.UPLOAD_PHOTO)
        await update.message.reply_photo(png_data, filename=f"{client.uid}.png", allow_sending_without_reply=True)
