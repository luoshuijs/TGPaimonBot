import os
import json

import genshin
from genshin import GenshinException, DataNotPublic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, ConversationHandler, filters, \
    CallbackQueryHandler

from logger import Log
from model.base import ServiceEnum
from plugins.base import BasePlugins, restricts
from plugins.errorhandler import conversation_error_handler
from service import BaseService
from service.base import UserInfoData


class UidCommandData:
    user_info: UserInfoData = UserInfoData()


class Ledger(BasePlugins):
    """
    旅行扎记
    """

    COMMAND_RESULT, = range(10200, 10201)

    def __init__(self, service: BaseService):
        super().__init__(service)
        self.current_dir = os.getcwd()

    @staticmethod
    def create_conversation_handler(service: BaseService):
        ledger = Ledger(service)
        return ConversationHandler(
            entry_points=[CommandHandler('ledger', ledger.command_start, block=True),
                          MessageHandler(filters.Regex(r"^旅行扎记(.*)"), ledger.command_start, block=True)],
            states={
                ledger.COMMAND_RESULT: [CallbackQueryHandler(ledger.command_result, block=True)]
            },
            fallbacks=[CommandHandler('cancel', ledger.cancel, block=True)]
        )

    async def _start_get_ledger(self, user_info_data: UserInfoData, service: ServiceEnum) -> bytes:
        if service == ServiceEnum.HYPERION:
            client = genshin.ChineseClient(cookies=user_info_data.mihoyo_cookie)
            uid = user_info_data.mihoyo_game_uid
        else:
            client = genshin.GenshinClient(cookies=user_info_data.hoyoverse_cookie, lang="zh-cn")
            uid = user_info_data.hoyoverse_game_uid
        try:
            diary_info = await client.get_diary(uid)
        except GenshinException as error:
            raise error
        color = ["#73a9c6", "#d56565", "#70b2b4", "#bd9a5a", "#739970", "#7a6da7", "#597ea0"]
        categories = [{"id": i.id,
                       "name": i.name,
                       "color": color[i.id % len(color)],
                       "amount": i.amount,
                       "percentage": i.percentage} for i in diary_info.month_data.categories]
        color = [i["color"] for i in categories]

        def format_amount(amount: int) -> str:
            return f"{round(amount / 10000, 2)}w" if amount >= 10000 else amount

        evaluate = """const { Pie } = G2Plot;
    const data = JSON.parse(`""" + json.dumps(categories) + """`);
    const piePlot = new Pie("chartContainer", {
      renderer: "svg",
      animation: false,
      data: data,
      appendPadding: 10,
      angleField: "amount",
      colorField: "name",
      radius: 1,
      innerRadius: 0.7,
      color: JSON.parse(`""" + json.dumps(color) + """`),
      meta: {},
      label: {
        type: "inner",
        offset: "-50%",
        autoRotate: false,
        style: {
          textAlign: "center",
          fontFamily: "tttgbnumber",
        },
        formatter: ({ percentage }) => {
          return percentage > 2 ? `${percentage}%` : "";
        },
      },
      statistic: {
        title: {
          offsetY: -18,
          content: "总计",
        },
        content: {
          offsetY: -10,
          style: {
            fontFamily: "tttgbnumber",
          },
        },
      },
      legend:false,
    });
    piePlot.render();"""
        ledger_data = {
            "uid": uid,
            "day": diary_info.month,
            "current_primogems": format_amount(diary_info.month_data.current_primogems),
            "gacha": int(diary_info.month_data.current_primogems / 160),
            "current_mora": format_amount(diary_info.month_data.current_mora),
            "last_primogems": format_amount(diary_info.month_data.last_primogems),
            "last_gacha": int(diary_info.month_data.last_primogems / 160),
            "last_mora": format_amount(diary_info.month_data.last_mora),
            "categories": categories,
        }
        png_data = await self.service.template.render('genshin/ledger', "ledger.html", ledger_data,
                                                      {"width": 580, "height": 610},
                                                      evaluate=evaluate,
                                                      auto_escape=False)
        return png_data

    @conversation_error_handler
    @restricts(return_data=ConversationHandler.END)
    async def command_start(self, update: Update, context: CallbackContext) -> int:
        user = update.effective_user
        message = update.message
        Log.info(f"用户 {user.full_name}[{user.id}] 查询原石手扎")
        ledger_command_data: UidCommandData = context.chat_data.get("ledger_command_data")
        if ledger_command_data is None:
            ledger_command_data = UidCommandData()
            context.chat_data["ledger_command_data"] = ledger_command_data
        user_info = await self.service.user_service_db.get_user_info(user.id)
        if user_info.user_id == 0:
            reply_message = await message.reply_text("未查询到账号信息，请先私聊派蒙绑定账号")
            if filters.ChatType.GROUPS.filter(message):
                self._add_delete_message_job(context, reply_message.chat_id, reply_message.message_id, 300)
                self._add_delete_message_job(context, message.chat_id, message.message_id, 300)
            return ConversationHandler.END
        if user_info.service == ServiceEnum.NULL:
            reply_text = "请选择你要查询的类别"
            keyboard = [
                [
                    InlineKeyboardButton("米游社", callback_data="ledger|米游社"),
                    InlineKeyboardButton("HoYoLab", callback_data="ledger|HoYoLab")
                ]
            ]
            ledger_command_data.user_info = user_info
            await update.message.reply_text(reply_text, reply_markup=InlineKeyboardMarkup(keyboard))
            return self.COMMAND_RESULT
        else:
            await update.message.reply_chat_action(ChatAction.TYPING)
            try:
                png_data = await self._start_get_ledger(user_info, user_info.service)
            except DataNotPublic:
                reply_message = await update.message.reply_text("查询失败惹，可能是手扎功能被禁用了？")
                if filters.ChatType.GROUPS.filter(message):
                    self._add_delete_message_job(context, reply_message.chat_id, reply_message.message_id, 300)
                    self._add_delete_message_job(context, message.chat_id, message.message_id, 300)
                return ConversationHandler.END
            await update.message.reply_chat_action(ChatAction.UPLOAD_PHOTO)
            await update.message.reply_photo(png_data, filename=f"{user_info.user_id}.png",
                                             allow_sending_without_reply=True)

        return ConversationHandler.END

    @conversation_error_handler
    async def command_result(self, update: Update, context: CallbackContext) -> int:
        get_user_command_data: UidCommandData = context.chat_data["ledger_command_data"]
        query = update.callback_query
        await query.answer()
        await query.delete_message()
        if query.data == "ledger|米游社":
            service = ServiceEnum.HYPERION
        elif query.data == "ledger|HoYoLab":
            service = ServiceEnum.HOYOLAB
        else:
            return ConversationHandler.END
        png_data = await self._start_get_ledger(get_user_command_data.user_info, service)
        await query.message.reply_chat_action(ChatAction.UPLOAD_PHOTO)
        await query.message.reply_photo(png_data, filename=f"{get_user_command_data.user_info.user_id}.png",
                                        allow_sending_without_reply=True)
        return ConversationHandler.END