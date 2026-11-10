import discord
from discord.ext import commands, tasks
import requests
import datetime
import urllib.parse
import json
import os

# ==========================================
# 설정 영역 (환경 변수 또는 직접 입력)
# ==========================================
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN")
LOSTARK_API_KEY = os.environ.get("LOSTARK_API_KEY", "YOUR_LOSTARK_API_KEY")
DATA_FILE = "user_data.json"

# ==========================================
# 데이터 저장 및 불러오기 함수
# ==========================================
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("db", {}), data.get("cache", {})
        except Exception as e:
            print(f"데이터 불러오기 실패: {e}")
    return {}, {}

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"db": user_character_db, "cache": user_name_cache}, f, ensure_ascii=False, indent=4)
        print("데이터 저장 완료")
    except Exception as e:
        print(f"데이터 저장 실패: {e}")

# 전역 데이터 로드
user_character_db, user_name_cache = load_data()

# ==========================================
# 로스트아크 API 호출 함수
# ==========================================
def get_lostark_character_info(character_name):
    encoded_name = urllib.parse.quote(character_name)
    url = f"https://developer-lostark.game.onstove.com/armories/profiles/{encoded_name}"
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {LOSTARK_API_KEY}"
    }
    try:
        response = requests.get(url, headers=headers, timeout=5)
        print(f"[{character_name}] API 응답 상태 코드: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            
            if data and "ItemMaxLevel" in data:
                level_str = str(data["ItemMaxLevel"]).replace(",", "")
                return float(level_str)
            else:
                print(f"응답 데이터에 ItemMaxLevel 없음: {data}")
        else:
            print(f"API 요청 실패: {response.text}")
            
    except Exception as e:
        print(f"API 호출 예외 발생: {e}")
    return None

# ==========================================
# 메인 제어 패널 (서버 전체 공용 버튼)
# ==========================================
class MainControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="[내 캐릭터 & 숙제 관리 열기]", style=discord.ButtonStyle.primary, custom_id="btn_open_my_panel")
    async def open_my_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        user_name_cache[user_id] = interaction.user.display_name
        if user_id not in user_character_db:
            user_character_db[user_id] = {}
        save_data()

        view = UserPanel(user_id)
        embed = view.generate_embed(interaction.user.display_name)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="[전체 유저 레이드 현황 보기]", style=discord.ButtonStyle.success, custom_id="btn_open_all_status")
    async def open_all_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AllStatusView()
        embed = view.generate_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ==========================================
# 유저 개인 관리 패널 View
# ==========================================
class UserPanel(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id

    def generate_embed(self, username):
        user_data = user_character_db.get(self.user_id, {})
        embed = discord.Embed(
            title=f"[숙제 관리] {username} 님의 캐릭터 현황",
            description="버튼을 눌러 캐릭터를 추가하거나 레이드 체크 상태를 변경하세요.",
            color=discord.Color.blue()
        )

        if not user_data:
            embed.add_field(name="등록된 캐릭터 없음", value="[캐릭터 추가] 버튼을 눌러 캐릭터를 등록해 주세요.", inline=False)
            return embed

        for char_name, info in user_data.items():
            field_value = f"Lv. {info['level']}\n"
            if not info["raids"]:
                field_value += "등록된 레이드 없음\n"
            else:
                for raid_name, is_cleared in info["raids"].items():
                    status = "[O]" if is_cleared else "[X]"
                    field_value += f"{status} {raid_name}\n"
            
            embed.add_field(name=f"캐릭터: {char_name}", value=field_value, inline=True)

        return embed

    @discord.ui.button(label="캐릭터 추가", style=discord.ButtonStyle.success, custom_id="btn_add_char_personal")
    async def add_char(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AddCharModal(self.user_id, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="레이드 추가 / 체크 변경", style=discord.ButtonStyle.secondary, custom_id="btn_manage_raid")
    async def manage_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_data = user_character_db.get(self.user_id, {})
        if not user_data:
            await interaction.response.send_message("먼저 캐릭터를 추가해 주세요!", ephemeral=True)
            return

        select_view = RaidManageSelectView(self.user_id, self)
        await interaction.response.send_message("관리할 캐릭터나 레이드를 선택하세요:", view=select_view, ephemeral=True)

# ==========================================
# 전체 유저 레이드 계층형 요약 현황 View
# ==========================================
class AllStatusView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    def generate_embed(self):
        embed = discord.Embed(
            title="[서버 전체 레이드 숙제 현황]",
            description="서버에 등록된 모든 유저의 캐릭터 및 레이드 세부 진행 현황입니다.",
            color=discord.Color.gold()
        )

        if not user_character_db:
            embed.add_field(name="등록된 정보 없음", value="아직 등록된 캐릭터나 유저가 없습니다.", inline=False)
            return embed

        for user_id, characters in user_character_db.items():
            if not characters:
                continue
            
            username = user_name_cache.get(user_id, f"유저({user_id})")
            user_text = ""
            
            for char_name, info in characters.items():
                user_text += f" - 캐릭터: {char_name} (Lv.{info['level']})\n"
                
                if not info["raids"]:
                    user_text += "    ㄴ 등록된 레이드 없음\n"
                else:
                    for raid_name, is_cleared in info["raids"].items():
                        ox_mark = "O" if is_cleared else "X"
                        user_text += f"    ㄴ {raid_name} : ({ox_mark})\n"
            
            embed.add_field(name=f"유저: {username}", value=user_text, inline=False)

        return embed

    @discord.ui.button(label="새로고침", style=discord.ButtonStyle.primary, custom_id="btn_refresh_all_status")
    async def refresh_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = self.generate_embed()
        await interaction.response.edit_message(embed=embed, view=self)

# ==========================================
# 개인 캐릭터 등록 Modal
# ==========================================
class AddCharModal(discord.ui.Modal, title="내 캐릭터 등록"):
    char_name = discord.ui.TextInput(label="캐릭터 이름", placeholder="정확한 캐릭터 명 입력", required=True)
    raids_input = discord.ui.TextInput(
        label="갈 레이드 목록 (쉼표로 구분)",
        placeholder="예: 발탄, 비아키스, 쿠크세이튼",
        default="발탄, 비아키스, 쿠크세이튼",
        required=True
    )

    def __init__(self, user_id, parent_view):
        super().__init__()
        self.user_id = user_id
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        name = self.char_name.value.strip()
        raids = [r.strip() for r in self.raids_input.value.split(",") if r.strip()]

        level = get_lostark_character_info(name)
        if level is None:
            level = 0.0

        if self.user_id not in user_character_db:
            user_character_db[self.user_id] = {}

        user_character_db[self.user_id][name] = {
            "level": level,
            "raids": {raid: False for raid in raids}
        }
        save_data()

        embed = self.parent_view.generate_embed(interaction.user.display_name)
        await interaction.response.edit_message(embed=embed, view=self.parent_view)
        await interaction.followup.send(f"'{name}' 캐릭터가 등록되었습니다!", ephemeral=True)

# ==========================================
# 레이드 체크 및 관리 셀렉트 메뉴
# ==========================================
class RaidManageSelectView(discord.ui.View):
    def __init__(self, user_id, parent_view):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.parent_view = parent_view

        user_data = user_character_db.get(user_id, {})
        options = []
        for char_name, info in user_data.items():
            for raid_name, is_cleared in info["raids"].items():
                status_text = "클리어 완료 (취소하기)" if is_cleared else "미클리어 (체크하기)"
                options.append(
                    discord.SelectOption(
                        label=f"[{char_name}] {raid_name}",
                        description=status_text,
                        value=f"{char_name}:{raid_name}"
                    )
                )

        if options:
            select = discord.ui.Select(placeholder="상태를 변경할 레이드를 선택하세요", options=options[:25])
            select.callback = self.select_callback
            self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        selected_value = interaction.data["values"][0]
        char_name, raid_name = selected_value.split(":")

        current_status = user_character_db[self.user_id][char_name]["raids"][raid_name]
        user_character_db[self.user_id][char_name]["raids"][raid_name] = not current_status
        save_data()

        await interaction.response.send_message(f"'{char_name}'의 '{raid_name}' 클리어 상태가 변경되었습니다!", ephemeral=True)
        
        embed = self.parent_view.generate_embed(interaction.user.display_name)
        try:
            await interaction.message.edit(embed=embed, view=self.parent_view)
        except Exception:
            pass

# ==========================================
# 봇 클래스 정의 및 주기적 태스크
# ==========================================
class LostArkBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        if not weekly_reset_task.is_running():
            weekly_reset_task.start()

    async def on_ready(self):
        print(f"로그인 완료: {self.user.name}")

@tasks.loop(minutes=1)
async def weekly_reset_task():
    now = datetime.datetime.now()
    if now.weekday() == 2 and now.hour == 6 and now.minute == 0:
        for user_id in user_character_db:
            for char in user_character_db[user_id].values():
                for raid in char["raids"]:
                    char["raids"][raid] = False
        save_data()
        print("모든 유저의 주간 숙제 자동 초기화 완료")

bot = LostArkBot()

@bot.command(name="숙제판")
async def show_main_panel(ctx):
    view = MainControlView()
    embed = discord.Embed(
        title="로스트아크 주간 숙제 통합 관리",
        description="버튼을 눌러 본인만의 숙제 관리창을 열거나, 서버 전체 유저의 세부 현황을 확인할 수 있습니다.",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed, view=view)

@bot.command(name="도움말")
async def show_help(ctx):
    embed = discord.Embed(
        title="로스트아크 숙제 봇 도움말",
        description="서버 멤버 누구나 자유롭게 이용할 수 있는 숙제 체크리스트 봇입니다.",
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="명령어 안내",
        value=(
            "!숙제판 : 메인 제어판(내 숙제 관리 및 전체 현황 버튼)을 생성합니다.\n"
            "!도움말 : 지금 보고 계신 도움말 안내창을 띄웁니다."
        ),
        inline=False
    )
    embed.add_field(
        name="이용 방법",
        value=(
            "1. !숙제판을 입력해 메인 패널을 소환하세요.\n"
            "2. [내 캐릭터 & 숙제 관리 열기] 버튼을 눌러 본인만의 관리창을 엽니다.\n"
            "3. [캐릭터 추가]로 로아 캐릭터를 등록하면 아이템 레벨이 자동 연동됩니다.\n"
            "4. [레이드 추가 / 체크 변경]으로 레이드별 클리어 상태를 변경할 수 있습니다.\n"
            "5. [전체 유저 레이드 현황 보기]를 통해 서버원들의 진행도를 확인할 수 있습니다.\n"
            "(매주 수요일 오전 6시에 모든 숙제 체크 상태가 자동으로 초기화됩니다.)"
        ),
        inline=False
    )
    await ctx.send(embed=embed)

bot.run(DISCORD_TOKEN)
