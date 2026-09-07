from io import BytesIO
from zoneinfo import ZoneInfo

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont, ImageOps
from redbot.core import Config, commands
from redbot.core.bot import Red


ITALY_TZ = ZoneInfo("Europe/Rome")


class Welcome(commands.Cog):
    """Invia un welcome personalizzato con immagine generata automaticamente."""

    __author__ = "danyx64"
    __version__ = "2.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self._background_cache = {}
        self.config = Config.get_conf(self, identifier=581244918377421006, force_registration=True)
        self.config.register_guild(
            enabled=False,
            channel_id=None,
            message="Benvenuto {user} in {guild}! Sei il membro numero {member_count}.",
            image_message="Benvenuto {displayname} su {guild}",
            background_url=None,
        )

    @staticmethod
    def _values(member: discord.Member) -> dict:
        guild = member.guild
        now = discord.utils.utcnow().astimezone(ITALY_TZ)
        created = member.created_at.astimezone(ITALY_TZ)
        joined = member.joined_at.astimezone(ITALY_TZ) if member.joined_at else None
        avatar = member.display_avatar.url if member.display_avatar else ""
        return {
            "user": member.mention,
            "mention": member.mention,
            "user_mention": member.mention,
            "username": member.name,
            "displayname": member.display_name,
            "user_tag": str(member),
            "user_id": str(member.id),
            "user_avatar": avatar,
            "guild": guild.name,
            "server": guild.name,
            "guild_id": str(guild.id),
            "server_id": str(guild.id),
            "member_count": str(guild.member_count or len(guild.members)),
            "date": now.strftime("%d/%m/%Y"),
            "time": now.strftime("%H:%M:%S"),
            "datetime": now.strftime("%d/%m/%Y %H:%M:%S"),
            "account_created": created.strftime("%d/%m/%Y %H:%M:%S"),
            "joined_at": joined.strftime("%d/%m/%Y %H:%M:%S") if joined else "—",
        }

    @classmethod
    def _format_message(cls, member: discord.Member, template: str, *, limit: int = 2000) -> str:
        result = str(template)
        for key, value in cls._values(member).items():
            result = result.replace("{" + key + "}", value)
        return result[:limit]

    @staticmethod
    def _font(size: int, *, bold: bool = True):
        names = (
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        )
        for name in names:
            try:
                return ImageFont.truetype(name, size=size)
            except OSError:
                continue
        return ImageFont.load_default()

    @classmethod
    def _fit_text(cls, draw: ImageDraw.ImageDraw, text: str, max_width: int, max_size: int, min_size: int):
        text = " ".join(text.split()) or "Benvenuto!"
        for size in range(max_size, min_size - 1, -2):
            font = cls._font(size, bold=True)
            if draw.textbbox((0, 0), text, font=font, stroke_width=max(1, size // 24))[2] <= max_width:
                return font, [text]

        font = cls._font(min_size, bold=True)
        words = text.split()
        lines = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textbbox((0, 0), candidate, font=font, stroke_width=1)[2] <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return font, lines[:3]

    async def _get_background(self, guild_id: int, url: str | None) -> Image.Image:
        if not url:
            return Image.new("RGB", (1280, 720), (32, 36, 43))

        cached = self._background_cache.get(guild_id)
        if cached and cached[0] == url:
            raw = cached[1]
        else:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise ValueError(f"HTTP {response.status}")
                    if int(response.headers.get("Content-Length", 0) or 0) > 12 * 1024 * 1024:
                        raise ValueError("Immagine troppo grande")
                    raw = await response.read()
                    if len(raw) > 12 * 1024 * 1024:
                        raise ValueError("Immagine troppo grande")
            self._background_cache[guild_id] = (url, raw)

        image = Image.open(BytesIO(raw)).convert("RGB")
        if image.width < 320 or image.height < 180:
            raise ValueError("Risoluzione troppo piccola")

        max_side = 1920
        if max(image.size) > max_side:
            ratio = max_side / max(image.size)
            image = image.resize(
                (max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
                Image.Resampling.LANCZOS,
            )
        return image

    async def _build_welcome_image(self, member: discord.Member, image_template: str, background_url: str | None):
        background = await self._get_background(member.guild.id, background_url)
        canvas = background.convert("RGBA")
        width, height = canvas.size
        short_side = min(width, height)

        # Overlay leggero per mantenere leggibili avatar e testo su qualsiasi sfondo.
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 58))
        canvas = Image.alpha_composite(canvas, overlay)

        avatar_bytes = await member.display_avatar.replace(size=512, static_format="png").read()
        avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")

        avatar_size = max(96, min(int(short_side * 0.30), int(height * 0.42), int(width * 0.34)))
        avatar = ImageOps.fit(avatar, (avatar_size, avatar_size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        mask = Image.new("L", (avatar_size, avatar_size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, avatar_size - 1, avatar_size - 1), fill=255)
        avatar.putalpha(mask)

        draw = ImageDraw.Draw(canvas)
        title = self._format_message(member, image_template, limit=300)
        max_text_width = int(width * 0.84)
        max_font = max(28, min(int(short_side * 0.075), 88))
        min_font = max(18, min(int(short_side * 0.035), 42))
        font, lines = self._fit_text(draw, title, max_text_width, max_font, min_font)
        stroke = max(1, int(short_side * 0.004))
        line_gap = max(4, int(short_side * 0.012))
        avatar_text_gap = max(16, int(short_side * 0.045))

        line_boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=stroke) for line in lines]
        line_heights = [box[3] - box[1] for box in line_boxes]
        text_height = sum(line_heights) + line_gap * max(0, len(lines) - 1)
        group_height = avatar_size + avatar_text_gap + text_height

        # Avatar + testo sono trattati come un unico gruppo centrato sull'immagine.
        group_top = max(int(height * 0.05), (height - group_height) // 2)
        avatar_x = (width - avatar_size) // 2
        avatar_y = group_top

        # Bordo circolare proporzionale alla risoluzione.
        border = max(3, int(short_side * 0.007))
        draw.ellipse(
            (avatar_x - border, avatar_y - border, avatar_x + avatar_size + border, avatar_y + avatar_size + border),
            fill=(255, 255, 255, 220),
        )
        canvas.alpha_composite(avatar, (avatar_x, avatar_y))

        y = avatar_y + avatar_size + avatar_text_gap
        for line, box, line_height in zip(lines, line_boxes, line_heights):
            line_width = box[2] - box[0]
            x = (width - line_width) // 2
            draw.text(
                (x, y),
                line,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=stroke,
                stroke_fill=(0, 0, 0, 210),
            )
            y += line_height + line_gap

        output = BytesIO()
        canvas.convert("RGB").save(output, format="JPEG", quality=92, optimize=True)
        output.seek(0)
        return output

    async def _send_welcome(self, member: discord.Member, *, force: bool = False):
        data = await self.config.guild(member.guild).all()
        if not force and not data.get("enabled"):
            return False

        channel_id = data.get("channel_id")
        if not channel_id:
            return False
        channel = member.guild.get_channel(int(channel_id))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return False

        me = member.guild.me
        if me is None:
            return False
        perms = channel.permissions_for(me)
        if not (perms.view_channel and perms.send_messages and perms.attach_files):
            return False

        content = self._format_message(member, str(data.get("message") or "Benvenuto {user}!"))
        image_template = str(data.get("image_message") or "Benvenuto {displayname} su {guild}")

        try:
            image = await self._build_welcome_image(member, image_template, data.get("background_url"))
            await channel.send(
                content,
                file=discord.File(image, filename="welcome.jpg"),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False, replied_user=False),
            )
            return True
        except (discord.Forbidden, discord.HTTPException, aiohttp.ClientError, OSError, ValueError):
            return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        await self._send_welcome(member)

    @commands.group(name="welcome", invoke_without_command=True)
    @commands.guild_only()
    async def welcome(self, ctx: commands.Context):
        """Configura il messaggio e l'immagine di benvenuto."""
        await ctx.send_help(ctx.command)

    @welcome.command(name="setchannel")
    @commands.admin_or_permissions(administrator=True)
    async def welcome_setchannel(self, ctx: commands.Context, channel_id: int):
        """Imposta il canale di benvenuto usando il suo ID."""
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await ctx.send("Non trovo un canale testuale con questo ID.")
        perms = channel.permissions_for(ctx.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.attach_files):
            return await ctx.send("Mi servono Visualizza canale, Invia messaggi e Allega file in quel canale.")
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"Canale welcome impostato su {channel.mention} (`{channel.id}`).")

    @welcome.command(name="message")
    @commands.admin_or_permissions(administrator=True)
    async def welcome_message(self, ctx: commands.Context, *, text: str):
        """Imposta il messaggio Discord inviato insieme all'immagine."""
        if not text.strip():
            return await ctx.send("Il messaggio non può essere vuoto.")
        if len(text) > 2000:
            return await ctx.send("Il messaggio non può superare 2000 caratteri.")
        await self.config.guild(ctx.guild).message.set(text)
        await ctx.send("Messaggio Discord aggiornato. Usa `.welcome preview` per provarlo.")

    @welcome.command(name="imagemessage", aliases=["imagetext"])
    @commands.admin_or_permissions(administrator=True)
    async def welcome_imagemessage(self, ctx: commands.Context, *, text: str):
        """Imposta il testo centrato sotto l'avatar nell'immagine."""
        if not text.strip():
            return await ctx.send("Il testo immagine non può essere vuoto.")
        if len(text) > 300:
            return await ctx.send("Il testo immagine non può superare 300 caratteri.")
        await self.config.guild(ctx.guild).image_message.set(text)
        await ctx.send("Testo dell'immagine aggiornato. Usa `.welcome preview` per provarlo.")

    @welcome.command(name="background", aliases=["bg"])
    @commands.admin_or_permissions(administrator=True)
    async def welcome_background(self, ctx: commands.Context, url: str = None):
        """Imposta lo sfondo da URL oppure dall'immagine allegata al comando."""
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            if not (attachment.content_type or "").startswith("image/"):
                return await ctx.send("L'allegato deve essere un'immagine.")
            url = attachment.url
        if not url:
            return await ctx.send("Passa un URL immagine oppure allega direttamente l'immagine al comando.")
        if not url.lower().startswith(("http://", "https://")):
            return await ctx.send("L'URL dello sfondo deve iniziare con http:// o https://.")
        await self.config.guild(ctx.guild).background_url.set(url)
        self._background_cache.pop(ctx.guild.id, None)
        await ctx.send("Sfondo welcome aggiornato. Usa `.welcome preview` per controllare il risultato.")

    @welcome.command(name="clearbackground", aliases=["clearbg"])
    @commands.admin_or_permissions(administrator=True)
    async def welcome_clearbackground(self, ctx: commands.Context):
        """Rimuove lo sfondo personalizzato e usa quello neutro predefinito."""
        await self.config.guild(ctx.guild).background_url.set(None)
        self._background_cache.pop(ctx.guild.id, None)
        await ctx.send("Sfondo personalizzato rimosso.")

    @welcome.command(name="view")
    @commands.admin_or_permissions(manage_guild=True)
    async def welcome_view(self, ctx: commands.Context):
        """Mostra i testi attualmente configurati."""
        data = await self.config.guild(ctx.guild).all()
        await ctx.send(
            f"Messaggio Discord:\n```\n{data.get('message')}\n```\n"
            f"Testo immagine:\n```\n{data.get('image_message')}\n```",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @welcome.command(name="usage", aliases=["placeholders"])
    @commands.admin_or_permissions(manage_guild=True)
    async def welcome_usage(self, ctx: commands.Context):
        """Mostra tutti i placeholder disponibili nei due messaggi."""
        text = (
            "**Placeholder disponibili**\n"
            "`{user}` / `{mention}` / `{user_mention}` → menzione del membro\n"
            "`{username}` → username\n"
            "`{displayname}` → nome visualizzato\n"
            "`{user_tag}` → nome Discord completo\n"
            "`{user_id}` → ID utente\n"
            "`{user_avatar}` → URL avatar\n"
            "`{guild}` / `{server}` → nome del server\n"
            "`{guild_id}` / `{server_id}` → ID del server\n"
            "`{member_count}` → numero membri\n"
            "`{date}` → data\n"
            "`{time}` → ora\n"
            "`{datetime}` → data e ora\n"
            "`{account_created}` → creazione account Discord\n"
            "`{joined_at}` → ingresso nel server\n\n"
            "**Esempi**\n"
            "`.welcome message Benvenuto {user}! Sei il membro numero {member_count}.`\n"
            "`.welcome imagemessage Benvenuto {displayname} su {guild}`\n"
            "`.welcome background https://.../sfondo.png` oppure allega l'immagine al comando."
        )
        await ctx.send(text, allowed_mentions=discord.AllowedMentions.none())

    @welcome.command(name="enable")
    @commands.admin_or_permissions(administrator=True)
    async def welcome_enable(self, ctx: commands.Context):
        """Abilita i messaggi di benvenuto."""
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("Welcome abilitato.")

    @welcome.command(name="disable")
    @commands.admin_or_permissions(administrator=True)
    async def welcome_disable(self, ctx: commands.Context):
        """Disabilita i messaggi di benvenuto."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("Welcome disabilitato.")

    @welcome.command(name="status")
    @commands.admin_or_permissions(manage_guild=True)
    async def welcome_status(self, ctx: commands.Context):
        """Mostra stato, canale e configurazione welcome."""
        data = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(data.get("channel_id")) if data.get("channel_id") else None
        await ctx.send(
            f"Stato: **{'attivo' if data.get('enabled') else 'disattivato'}**\n"
            f"Canale: {channel.mention if channel else '—'}\n"
            f"Messaggio Discord: `{data.get('message')}`\n"
            f"Testo immagine: `{data.get('image_message')}`\n"
            f"Sfondo: {'configurato' if data.get('background_url') else 'predefinito'}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @welcome.command(name="preview", aliases=["test"])
    @commands.admin_or_permissions(manage_guild=True)
    async def welcome_preview(self, ctx: commands.Context):
        """Invia nel canale configurato un'anteprima usando il tuo account."""
        ok = await self._send_welcome(ctx.author, force=True)
        if ok:
            await ctx.send("Anteprima inviata nel canale welcome.")
        else:
            await ctx.send(
                "Non sono riuscito a generare o inviare l'anteprima. Controlla `.welcome status`, "
                "lo sfondo e i permessi Visualizza canale / Invia messaggi / Allega file."
            )
