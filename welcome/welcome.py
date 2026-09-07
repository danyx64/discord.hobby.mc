import logging
from io import BytesIO
from zoneinfo import ZoneInfo

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from redbot.core import Config, commands
from redbot.core.bot import Red

ITALY_TZ = ZoneInfo("Europe/Rome")
log = logging.getLogger("red.danyx64.welcome")


class Welcome(commands.Cog):
    """Invia un welcome personalizzato con immagine generata automaticamente."""

    __author__ = "danyx64"
    __version__ = "2.4.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self._background_cache = {}
        self._last_error = None
        self.config = Config.get_conf(self, identifier=581244918377421006, force_registration=True)
        self.config.register_guild(
            enabled=False,
            channel_id=None,
            message="Benvenuto {user} in {guild}! Sei il membro numero {member_count}.",
            image_message="Benvenuto\n{globalname}\nin {guild}",
            background_url=None,
        )

    @staticmethod
    def _values(member: discord.Member) -> dict:
        guild = member.guild
        now = discord.utils.utcnow().astimezone(ITALY_TZ)
        created = member.created_at.astimezone(ITALY_TZ)
        joined = member.joined_at.astimezone(ITALY_TZ) if member.joined_at else None
        avatar = member.display_avatar.url if member.display_avatar else ""
        global_name = member.global_name or member.name
        return {
            "user": member.mention,
            "mention": member.mention,
            "user_mention": member.mention,
            "username": member.name,
            "globalname": global_name,
            "discordname": global_name,
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
    def _format_message(cls, member, template, *, limit=2000):
        result = str(template)
        for key, value in cls._values(member).items():
            result = result.replace("{" + key + "}", value)
        return result[:limit]

    @staticmethod
    def _font(size, *, bold=True):
        names = (
            "/usr/share/fonts/truetype/inter/Inter-SemiBold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-SemiBold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ) if bold else (
            "/usr/share/fonts/truetype/inter/Inter-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        )
        for name in names:
            try:
                return ImageFont.truetype(name, size=size)
            except OSError:
                continue
        return ImageFont.load_default()

    async def _download_image(self, url, *, label, max_bytes=12 * 1024 * 1024):
        timeout = aiohttp.ClientTimeout(total=20)
        headers = {"User-Agent": "Red Welcome/2.4"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    raise ValueError(f"{label}: download fallito (HTTP {response.status})")
                ctype = (response.headers.get("Content-Type") or "").lower()
                if ctype and not ctype.startswith("image/"):
                    raise ValueError(f"{label}: URL non restituisce un'immagine ({ctype})")
                raw = await response.read()
                if not raw:
                    raise ValueError(f"{label}: file vuoto")
                if len(raw) > max_bytes:
                    raise ValueError(f"{label}: immagine troppo grande")
                return raw

    async def _get_background(self, guild_id, url):
        if not url:
            return Image.new("RGB", (1280, 720), (32, 36, 43))

        cached = self._background_cache.get(guild_id)
        raw = cached[1] if cached and cached[0] == url else await self._download_image(url, label="Sfondo")
        self._background_cache[guild_id] = (url, raw)

        try:
            image = Image.open(BytesIO(raw))
            image.load()
            image = ImageOps.exif_transpose(image).convert("RGB")
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError(f"Sfondo: formato non valido ({exc})") from exc

        if image.width < 320 or image.height < 180:
            raise ValueError("Sfondo: risoluzione minima 320x180")

        # Mantiene gli sfondi piccoli alla loro dimensione originale.
        # Gli sfondi grandi vengono ridotti per avere un welcome piu compatto su Discord.
        max_side = 1280
        if max(image.size) > max_side:
            ratio = max_side / max(image.size)
            new_size = (
                max(1, round(image.width * ratio)),
                max(1, round(image.height * ratio)),
            )
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        return image

    async def _get_avatar(self, member):
        try:
            raw = await member.display_avatar.replace(size=512, static_format="png").read()
            image = Image.open(BytesIO(raw))
            image.load()
            return image.convert("RGBA")
        except Exception as exc:
            raise ValueError(f"Avatar: impossibile leggere la PFP ({exc})") from exc

    @classmethod
    def _responsive_font(cls, draw, lines, short_side, max_width):
        # Tutte le righe condividono lo stesso font: il blocco rimane visivamente uniforme.
        wanted = max(14, round(short_side * 0.052))
        minimum = max(11, round(short_side * 0.026))

        for size in range(wanted, minimum - 1, -1):
            font = cls._font(size)
            if all(draw.textbbox((0, 0), line, font=font)[2] <= max_width for line in lines):
                return font
        return cls._font(minimum)

    async def _build_welcome_image(self, member, image_template, background_url):
        background = await self._get_background(member.guild.id, background_url)
        canvas = background.convert("RGBA")
        width, height = canvas.size
        short = min(width, height)

        # Oscuramento proporzionalmente identico su qualunque risoluzione.
        canvas = Image.alpha_composite(
            canvas,
            Image.new("RGBA", canvas.size, (0, 0, 0, 70)),
        )

        # Tutte le misure dipendono dal lato corto: nessuna dimensione fissa grossa.
        avatar_size = max(44, round(short * 0.235))
        avatar_size = min(avatar_size, round(height * 0.30))

        avatar = await self._get_avatar(member)
        avatar = ImageOps.fit(
            avatar,
            (avatar_size, avatar_size),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        mask = Image.new("L", (avatar_size, avatar_size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, avatar_size - 1, avatar_size - 1), fill=255)
        avatar.putalpha(mask)

        global_name = member.global_name or member.name
        lines = ["Benvenuto", global_name, f"in {member.guild.name}"]

        draw = ImageDraw.Draw(canvas)
        max_text_width = round(width * 0.76)
        font = self._responsive_font(draw, lines, short, max_text_width)

        # Altezza unica per ogni riga + gap unico: righe davvero equidistanti.
        line_boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
        line_height = max(box[3] - box[1] for box in line_boxes)
        line_gap = max(4, round(short * 0.015))
        avatar_gap = max(9, round(short * 0.030))

        text_block_height = (line_height * 3) + (line_gap * 2)
        group_height = avatar_size + avatar_gap + text_block_height
        group_top = max(round(height * 0.05), (height - group_height) // 2)

        avatar_x = (width - avatar_size) // 2
        canvas.alpha_composite(avatar, (avatar_x, group_top))

        y = group_top + avatar_size + avatar_gap
        shadow_offset = max(1, round(short * 0.0018))

        for line, box in zip(lines, line_boxes):
            line_width = box[2] - box[0]
            x = (width - line_width) // 2

            # Corregge l'offset verticale interno del font per centrare ogni riga nella sua cella.
            glyph_height = box[3] - box[1]
            text_y = y + ((line_height - glyph_height) // 2) - box[1]

            draw.text(
                (x + shadow_offset, text_y + shadow_offset),
                line,
                font=font,
                fill=(0, 0, 0, 105),
            )
            draw.text(
                (x, text_y),
                line,
                font=font,
                fill=(255, 255, 255, 255),
            )
            y += line_height + line_gap

        output = BytesIO()
        canvas.convert("RGB").save(output, format="JPEG", quality=90, optimize=True)
        output.seek(0)
        return output

    def _set_error(self, message):
        self._last_error = message
        return False

    async def _send_welcome(self, member, *, force=False):
        self._last_error = None
        data = await self.config.guild(member.guild).all()

        if not force and not data.get("enabled"):
            return self._set_error("Welcome disabilitato")

        channel_id = data.get("channel_id")
        channel = member.guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return self._set_error("Canale welcome non configurato o non valido")

        me = member.guild.me
        if me is None:
            return self._set_error("Membro bot non disponibile")

        perms = channel.permissions_for(me)
        if not (perms.view_channel and perms.send_messages and perms.attach_files):
            return self._set_error("Permessi mancanti nel canale welcome")

        content = self._format_message(member, data.get("message") or "Benvenuto {mention}!")

        try:
            image = await self._build_welcome_image(
                member,
                data.get("image_message"),
                data.get("background_url"),
            )
            await channel.send(
                content,
                file=discord.File(image, filename="welcome.jpg"),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
            return True
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"[:1000]
            log.exception("Errore welcome per %s", member.id)
            return False

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not member.bot:
            await self._send_welcome(member)

    @commands.group(name="welcome", invoke_without_command=True)
    @commands.guild_only()
    async def welcome(self, ctx):
        await ctx.send_help(ctx.command)

    @welcome.command(name="setchannel")
    @commands.admin_or_permissions(administrator=True)
    async def welcome_setchannel(self, ctx, channel_id: int):
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await ctx.send("Non trovo un canale testuale con questo ID.")
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"Canale welcome impostato su {channel.mention}.")

    @welcome.command(name="message")
    @commands.admin_or_permissions(administrator=True)
    async def welcome_message(self, ctx, *, text: str):
        await self.config.guild(ctx.guild).message.set(text[:2000])
        await ctx.send("Messaggio Discord aggiornato.")

    @welcome.command(name="imagemessage", aliases=["imagetext"])
    @commands.admin_or_permissions(administrator=True)
    async def welcome_imagemessage(self, ctx, *, text: str):
        await self.config.guild(ctx.guild).image_message.set(text[:300])
        await ctx.send(
            "Testo salvato. Il layout grafico usa automaticamente Benvenuto / nome Discord / nome server."
        )

    @welcome.command(name="background", aliases=["bg"])
    @commands.admin_or_permissions(administrator=True)
    async def welcome_background(self, ctx, url: str = None):
        if ctx.message.attachments:
            url = ctx.message.attachments[0].url
        if not url or not url.lower().startswith(("http://", "https://")):
            return await ctx.send("Passa un URL immagine valido oppure allega un'immagine.")

        try:
            raw = await self._download_image(url, label="Sfondo")
            test = Image.open(BytesIO(raw))
            test.load()
        except Exception as exc:
            return await ctx.send(
                f"Sfondo non valido: `{type(exc).__name__}: {str(exc)[:500]}`"
            )

        await self.config.guild(ctx.guild).background_url.set(url)
        self._background_cache[ctx.guild.id] = (url, raw)
        await ctx.send(
            f"Sfondo aggiornato (`{test.width}x{test.height}`). PFP, font e spazi si adattano automaticamente."
        )

    @welcome.command(name="clearbackground", aliases=["clearbg"])
    @commands.admin_or_permissions(administrator=True)
    async def welcome_clearbackground(self, ctx):
        await self.config.guild(ctx.guild).background_url.set(None)
        self._background_cache.pop(ctx.guild.id, None)
        await ctx.send("Sfondo personalizzato rimosso.")

    @welcome.command(name="usage", aliases=["placeholders"])
    @commands.admin_or_permissions(manage_guild=True)
    async def welcome_usage(self, ctx):
        await ctx.send(
            "Placeholder: `{mention}`, `{username}`, `{globalname}`/`{discordname}` (nome Discord globale), "
            "`{displayname}` (nome visualizzato nel server), `{guild}`, `{member_count}`, `{date}`, `{time}`.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @welcome.command(name="enable")
    @commands.admin_or_permissions(administrator=True)
    async def welcome_enable(self, ctx):
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("Welcome abilitato.")

    @welcome.command(name="disable")
    @commands.admin_or_permissions(administrator=True)
    async def welcome_disable(self, ctx):
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("Welcome disabilitato.")

    @welcome.command(name="status")
    @commands.admin_or_permissions(manage_guild=True)
    async def welcome_status(self, ctx):
        data = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(data.get("channel_id")) if data.get("channel_id") else None
        await ctx.send(
            f"Versione cog: **{self.__version__}**\n"
            f"Stato: **{'attivo' if data.get('enabled') else 'disattivato'}**\n"
            f"Canale: {channel.mention if channel else '—'}\n"
            f"Sfondo: {'configurato' if data.get('background_url') else 'predefinito'}"
        )

    @welcome.command(name="preview", aliases=["test"])
    @commands.admin_or_permissions(manage_guild=True)
    async def welcome_preview(self, ctx):
        async with ctx.typing():
            ok = await self._send_welcome(ctx.author, force=True)
        if ok:
            await ctx.send("✅ Anteprima inviata nel canale welcome.")
        else:
            await ctx.send(
                f"❌ Welcome preview fallita: `{self._last_error or 'Errore sconosciuto'}`"
            )
