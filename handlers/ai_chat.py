# handlers/ai_chat.py
"""
AI对话处理器 - 集成多模型AI对话功能
适配自 aibot3.py，使用 python-telegram-bot 库
"""

import logging
import requests
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import config, Permissions
from data_manager import data_manager

logger = logging.getLogger(__name__)


class ModelType(Enum):
    """模型类型枚举"""
    GEMINI = "gemini"
    GPT = "GPT"


class PromptType(Enum):
    """Prompt类型枚举"""
    DEFAULT = "default"
    PROGRAMMER = "programmer"
    TEACHER = "teacher"
    WRITER = "writer"
    TRANSLATOR = "translator"


@dataclass
class AIConfig:
    """AI配置类"""
    CHATPUB_API_URL: str = "https://tbai.xin/v1/chat/completions"
    CHATPUB_API_KEY: str = "sk-AVD09rgEcpcEbUn0pQIBjdzWhk7H4SRelG69vC10rRS3nW0o"

    AVAILABLE_MODELS: Dict[str, str] = None
    DEFAULT_MODEL: ModelType = ModelType.GEMINI

    MSG_LENGTH_LIMIT: int = 4096
    CHAT_TIMEOUT_HOURS: int = 1
    API_TIMEOUT: int = 120

    def __post_init__(self):
        if self.AVAILABLE_MODELS is None:
            self.AVAILABLE_MODELS = {
                ModelType.GEMINI.value: 'gemini-2.0-flash-exp',
                ModelType.GPT.value: 'gpt-4o-mini'
            }


@dataclass
class PromptTemplate:
    """Prompt模板类"""
    name: str
    content: str
    description: str
    emoji: str


class PromptManager:
    """Prompt管理器"""

    def __init__(self):
        self._templates = self._initialize_templates()

    def _initialize_templates(self) -> Dict[str, PromptTemplate]:
        """初始化预设模板"""
        return {
            PromptType.DEFAULT.value: PromptTemplate(
                name="默认助手",
                emoji="🤖",
                description="友好、真实的AI助手",
                content="你是一个友好、专业的AI助手。你会用清晰、简洁的语言回答问题，并且总是保持礼貌和耐心。你会根据用户的需求提供准确的信息和建议。记得用中文回答。"
            ),
            PromptType.PROGRAMMER.value: PromptTemplate(
                name="编程专家",
                emoji="💻",
                description="经验丰富的程序员助手",
                content="你是一个经验丰富的程序员，擅长多种编程语言和框架。你会提供清晰、高效、有良好文档的代码解决方案。你会解释代码的工作原理，并给出最佳实践建议。"
            ),
            PromptType.TEACHER.value: PromptTemplate(
                name="耐心老师",
                emoji="👨‍🏫",
                description="善于解释复杂概念的老师",
                content="你是一个耐心的老师，擅长用简单的语言解释复杂的概念。你会将困难的主题分解成易于理解的步骤，并且会用例子和比喻来帮助学生理解。"
            ),
            PromptType.WRITER.value: PromptTemplate(
                name="创意写手",
                emoji="✍️",
                description="创意写作和内容创作助手",
                content="你是一个富有创意的作家，擅长写作和内容创作。你能提供引人入胜、结构良好、富有创意的内容。你会根据不同的风格和目的调整写作方式。"
            ),
            PromptType.TRANSLATOR.value: PromptTemplate(
                name="翻译专家",
                emoji="🌐",
                description="专业翻译和语言学习助手",
                content="你是一个专业的翻译专家，精通多国语言。你能提供准确的翻译，并解释语言细微差别。你会帮助用户理解不同语言的表达方式和文化背景。"
            )
        }

    def get_template(self, template_type: str) -> Optional[PromptTemplate]:
        """获取模板"""
        return self._templates.get(template_type)

    def get_all_templates(self) -> Dict[str, PromptTemplate]:
        """获取所有模板"""
        return self._templates.copy()


class UserSession:
    """用户会话类"""

    def __init__(self, user_id: int, model_key: str, prompt: str):
        self.user_id = user_id
        self.model_key = model_key
        self.prompt = prompt
        self.chat_history: List[Dict[str, str]] = []
        self.last_activity = datetime.now()
        self._initialize_chat()

    def _initialize_chat(self):
        """初始化对话历史"""
        self.chat_history = [{"role": "system", "content": self.prompt}]

    def add_message(self, role: str, content: str):
        """添加消息到历史"""
        self.chat_history.append({"role": role, "content": content})
        self.update_activity()

    def update_activity(self):
        """更新活动时间"""
        self.last_activity = datetime.now()

    def update_prompt(self, new_prompt: str):
        """更新prompt"""
        self.prompt = new_prompt
        for i, msg in enumerate(self.chat_history):
            if msg["role"] == "system":
                self.chat_history[i]["content"] = new_prompt
                break

    def update_model(self, new_model_key: str):
        """更新模型"""
        self.model_key = new_model_key

    def reset_chat(self):
        """重置对话历史"""
        self._initialize_chat()
        self.update_activity()

    def is_expired(self, timeout_hours: int) -> bool:
        """检查会话是否过期"""
        return (datetime.now() - self.last_activity) > timedelta(hours=timeout_hours)

    def get_messages_for_api(self) -> List[Dict[str, str]]:
        """获取用于API调用的消息"""
        return self.chat_history.copy()


class AIService:
    """AI服务类"""

    def __init__(self, ai_config: AIConfig):
        self.config = ai_config

    def chat(self, messages: List[Dict[str, str]], model: str) -> str:
        """与AI模型对话"""
        headers = {
            "Authorization": f"Bearer {self.config.CHATPUB_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model,
            "messages": messages
        }

        try:
            logger.info(f"Making API request to {model}")
            response = requests.post(
                self.config.CHATPUB_API_URL,
                json=payload,
                headers=headers,
                timeout=self.config.API_TIMEOUT
            )
            response.raise_for_status()

            result = response.json()
            return result['choices'][0]['message']['content']

        except requests.Timeout:
            raise Exception("⏱️ 请求超时，请稍后重试")
        except requests.ConnectionError:
            raise Exception("🌐 网络连接错误，请检查网络后重试")
        except requests.HTTPError as e:
            if e.response.status_code == 401:
                raise Exception("🔐 API密钥无效，请联系管理员")
            elif e.response.status_code == 429:
                raise Exception("⚡ 请求过于频繁，请稍后再试")
            elif e.response.status_code >= 500:
                raise Exception("🖥️ 服务器错误，请稍后重试")
            else:
                raise Exception(f"❌ HTTP {e.response.status_code}")
        except Exception as e:
            raise Exception(f"❌ 发生错误: {str(e)}")


class AIChatHandler:
    """AI对话处理器主类"""

    def __init__(self):
        self.ai_config = AIConfig()
        self.prompt_manager = PromptManager()
        self.ai_service = AIService(self.ai_config)
        self.sessions: Dict[int, UserSession] = {}
        self.user_states = {}

    def check_permission(self, user_id: int) -> bool:
        """检查用户权限"""
        user_permission = data_manager.get_user_permission(user_id)
        return user_permission != Permissions.BANNED

    def get_or_create_session(self, user_id: int) -> UserSession:
        """获取或创建用户会话"""
        if user_id not in self.sessions:
            default_template = self.prompt_manager.get_template(PromptType.DEFAULT.value)
            self.sessions[user_id] = UserSession(
                user_id=user_id,
                model_key=self.ai_config.DEFAULT_MODEL.value,
                prompt=default_template.content
            )
        return self.sessions[user_id]

    def get_session(self, user_id: int) -> Optional[UserSession]:
        """获取用户会话"""
        return self.sessions.get(user_id)

    def remove_session(self, user_id: int) -> bool:
        """移除用户会话"""
        if user_id in self.sessions:
            del self.sessions[user_id]
            return True
        return False

    def cleanup_expired_sessions(self):
        """清理过期会话"""
        expired_users = []
        for user_id, session in self.sessions.items():
            if session.is_expired(self.ai_config.CHAT_TIMEOUT_HOURS):
                expired_users.append(user_id)

        for user_id in expired_users:
            self.remove_session(user_id)
            logger.info(f"Cleaned up expired session for user {user_id}")

    async def show_ai_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """显示AI对话菜单"""
        query = update.callback_query
        if query:
            await query.answer()

        user_id = update.effective_user.id
        if not self.check_permission(user_id):
            message_text = "❌ 您没有权限使用AI对话功能"
            if query:
                await query.edit_message_text(message_text)
            else:
                await update.message.reply_text(message_text)
            return

        session = self.get_session(user_id)
        status_text = ""
        if session:
            model_name = self.ai_config.AVAILABLE_MODELS[session.model_key]
            message_count = len([m for m in session.chat_history if m["role"] != "system"])
            status_text = f"\n\n📊 **当前状态**:\n• 模型: {model_name}\n• 消息数: {message_count}"

        menu_text = f"🤖 **AI 对话助手**\n\n功能简介:\n• 多模型支持 (Gemini/GPT)\n• 角色预设系统\n• 自定义Prompt\n• 对话历史管理{status_text}"

        keyboard = [
            [
                InlineKeyboardButton("💬 开始对话", callback_data="ai_chat:start"),
                InlineKeyboardButton("🤖 切换模型", callback_data="ai_chat:model")
            ],
            [
                InlineKeyboardButton("🎭 选择角色", callback_data="ai_chat:preset"),
                InlineKeyboardButton("📝 自定义Prompt", callback_data="ai_chat:custom_prompt")
            ],
            [
                InlineKeyboardButton("🔄 重置对话", callback_data="ai_chat:reset"),
                InlineKeyboardButton("📊 查看状态", callback_data="ai_chat:status")
            ],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_start")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await query.edit_message_text(menu_text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(menu_text, reply_markup=reply_markup)

    async def start_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """开始对话"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        session = self.get_or_create_session(user_id)

        current_model = self.ai_config.AVAILABLE_MODELS[session.model_key]

        response_text = (
            f"✅ **对话已开始！**\n\n"
            f"📱 当前模型: `{current_model}`\n"
            f"💭 Prompt: {session.prompt[:80]}{'...' if len(session.prompt) > 80 else ''}\n\n"
            f"现在可以直接发送消息开始对话了\n\n"
            f"💡 提示: 使用 /ai_end 结束对话"
        )

        keyboard = [[InlineKeyboardButton("🔙 返回AI菜单", callback_data="ai_chat:menu")]]
        await query.edit_message_text(response_text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def select_model(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """选择模型"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        session = self.get_session(user_id)
        current_model_key = session.model_key if session else self.ai_config.DEFAULT_MODEL.value

        keyboard = []
        for key, model_name in self.ai_config.AVAILABLE_MODELS.items():
            is_current = key == current_model_key
            button_text = f"{'✅ ' if is_current else ''}{model_name}"
            if is_current:
                button_text += " (当前)"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"ai_model:{key}")])

        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="ai_chat:menu")])

        await query.edit_message_text(
            "🤖 **选择AI模型**\n\n请选择要使用的模型:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def handle_model_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理模型选择"""
        query = update.callback_query
        model_key = query.data.split(":")[1]

        user_id = update.effective_user.id
        session = self.get_or_create_session(user_id)
        session.update_model(model_key)

        model_name = self.ai_config.AVAILABLE_MODELS[model_key]
        await query.answer(f"✅ 已切换到: {model_name}")

        # 刷新模型选择菜单
        await self.select_model(update, context)

    async def select_preset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """选择角色预设"""
        query = update.callback_query
        await query.answer()

        keyboard = []
        templates = self.prompt_manager.get_all_templates()

        for key, template in templates.items():
            button_text = f"{template.emoji} {template.name}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"ai_preset:{key}")])

        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="ai_chat:menu")])

        await query.edit_message_text(
            "🎭 **选择角色预设**\n\n每个角色都有不同的专长和风格:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def handle_preset_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理预设选择"""
        query = update.callback_query
        preset_key = query.data.split(":")[1]

        template = self.prompt_manager.get_template(preset_key)
        if not template:
            await query.answer("❌ 无效的预设")
            return

        user_id = update.effective_user.id
        session = self.get_or_create_session(user_id)
        session.update_prompt(template.content)

        await query.answer(f"✅ 已切换到: {template.name}")

        response_text = (
            f"✅ **角色已切换**\n\n"
            f"{template.emoji} **{template.name}**\n"
            f"📝 描述: {template.description}\n\n"
            f"💭 Prompt:\n{template.content[:200]}{'...' if len(template.content) > 200 else ''}"
        )

        keyboard = [[InlineKeyboardButton("🔙 返回AI菜单", callback_data="ai_chat:menu")]]
        await query.edit_message_text(response_text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def prompt_custom_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """提示输入自定义Prompt"""
        query = update.callback_query
        await query.answer()

        self.user_states[update.effective_chat.id] = 'awaiting_custom_prompt'

        prompt_text = (
            "📝 **自定义 Prompt**\n\n"
            "请发送您的自定义Prompt内容\n\n"
            "💡 提示:\n"
            "• 描述AI助手的角色和能力\n"
            "• 指定回答的风格和语气\n"
            "• 最长2000字符\n\n"
            "发送 /cancel 取消操作"
        )

        keyboard = [[InlineKeyboardButton("❌ 取消", callback_data="ai_chat:menu")]]
        await query.edit_message_text(prompt_text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def handle_custom_prompt_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理自定义Prompt输入"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        if self.user_states.get(chat_id) != 'awaiting_custom_prompt':
            return

        new_prompt = update.message.text.strip()

        if len(new_prompt) == 0:
            await update.message.reply_text("❌ Prompt不能为空，请重新输入")
            return

        if len(new_prompt) > 2000:
            await update.message.reply_text("❌ Prompt太长（最大2000字符），请缩短后重试")
            return

        session = self.get_or_create_session(user_id)
        session.update_prompt(new_prompt)

        self.user_states.pop(chat_id, None)

        keyboard = [[InlineKeyboardButton("🔙 返回AI菜单", callback_data="ai_chat:menu")]]
        await update.message.reply_text(
            f"✅ **Prompt已更新！**\n\n"
            f"新内容:\n{new_prompt[:200]}{'...' if len(new_prompt) > 200 else ''}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def reset_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """重置对话"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        session = self.get_session(user_id)

        if not session:
            await query.edit_message_text("❌ 当前没有活跃的对话会话")
            return

        session.reset_chat()

        keyboard = [[InlineKeyboardButton("🔙 返回AI菜单", callback_data="ai_chat:menu")]]
        await query.edit_message_text(
            "✅ **对话历史已重置！**\n\n可以重新开始对话了",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def show_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """显示状态"""
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        session = self.get_session(user_id)

        if not session:
            status_text = "📊 **当前状态**\n\n❌ 没有活跃的对话会话\n\n使用 💬 开始对话"
        else:
            model_name = self.ai_config.AVAILABLE_MODELS[session.model_key]
            message_count = len([m for m in session.chat_history if m["role"] != "system"])
            activity_time = session.last_activity.strftime("%H:%M:%S")

            status_text = (
                f"📊 **当前状态**\n\n"
                f"✅ 会话状态: 活跃\n"
                f"🤖 使用模型: `{model_name}`\n"
                f"💬 消息数量: {message_count}\n"
                f"⏰ 最后活动: {activity_time}\n"
                f"📝 Prompt长度: {len(session.prompt)} 字符"
            )

        keyboard = [[InlineKeyboardButton("🔙 返回AI菜单", callback_data="ai_chat:menu")]]
        await query.edit_message_text(status_text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理AI对话消息"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        # 检查是否在等待自定义prompt输入
        if self.user_states.get(chat_id) == 'awaiting_custom_prompt':
            await self.handle_custom_prompt_input(update, context)
            return

        # 检查是否有活跃会话
        session = self.get_session(user_id)
        if not session:
            return  # 没有会话，让其他handler处理

        # 清理过期会话
        self.cleanup_expired_sessions()

        try:
            # 添加用户消息到历史
            session.add_message("user", update.message.text)

            # 发送"正在输入"状态
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")

            # 调用AI服务
            current_model = self.ai_config.AVAILABLE_MODELS[session.model_key]
            messages = session.get_messages_for_api()

            response = self.ai_service.chat(messages, current_model)

            # 添加AI回复到历史
            session.add_message("assistant", response)

            # 发送回复（处理长消息）
            await self._send_long_message(update, response)

        except Exception as e:
            error_msg = str(e)
            await update.message.reply_text(f"❌ 对话出错:\n{error_msg}")
            logger.error(f"AI chat error for user {user_id}: {e}")

    async def _send_long_message(self, update: Update, text: str):
        """处理长消息发送"""
        if len(text) <= self.ai_config.MSG_LENGTH_LIMIT:
            await update.message.reply_text(text)
        else:
            # 分段发送
            parts = self._split_message(text)
            for i, part in enumerate(parts):
                formatted_part = f"📄 [{i+1}/{len(parts)}]\n\n{part}" if len(parts) > 1 else part
                await update.message.reply_text(formatted_part)

    def _split_message(self, text: str) -> List[str]:
        """智能分割消息"""
        if len(text) <= self.ai_config.MSG_LENGTH_LIMIT:
            return [text]

        parts = []
        current_part = ""
        paragraphs = text.split('\n\n')

        for paragraph in paragraphs:
            if len(paragraph) > self.ai_config.MSG_LENGTH_LIMIT:
                sentences = paragraph.split('. ')
                for sentence in sentences:
                    if len(current_part + sentence + '. ') > self.ai_config.MSG_LENGTH_LIMIT:
                        if current_part:
                            parts.append(current_part.strip())
                        current_part = sentence + '. '
                    else:
                        current_part += sentence + '. '
            else:
                if len(current_part + paragraph + '\n\n') > self.ai_config.MSG_LENGTH_LIMIT:
                    if current_part:
                        parts.append(current_part.strip())
                    current_part = paragraph + '\n\n'
                else:
                    current_part += paragraph + '\n\n'

        if current_part.strip():
            parts.append(current_part.strip())

        return parts
