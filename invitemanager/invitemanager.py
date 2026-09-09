from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, Optional

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red


class InviteManager(commands.Cog):
    """Gestione centralizzata e sincronizzata degli inviti Discord."""

    __author__ = "danyx64"
    __version__ = "1.4.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xD15C0A11, force_registration=True)
        self.config.register_guild(invites={}, invite_channel_id=None)
        self._invite_cache: Dict[int, Dict[str, int]] = {}
        self._sync_lock = asyncio.Lock()

    async def cog_load(self) -> None:
        await self.bot.wait_until_red_ready()
        for guild in self.bot.guilds:
            await self._sync_guild(guild)
        self.auto_sync.start()

    def cog_unload(self) -> None:
        self.auto_sync.cancel()

    @staticmethod
    def _normalize_code(code: str) -> str:
        return code.rsplit("/", 1)[-1].strip()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    async def _get_record(self, guild: discord.Guild, code: str) -> Optional[dict]:
        invites = await self.config.guild(guild).invites()
        return invites.get(code)

    async def _save_record(self, guild: discord.Guild, code: str, data: dict) -> None:
        async with self.config.guild(guild).invites() as invites:
            invites[code] = data

    async def _delete_record(self, guild: discord.Guild, code: str) -> None:
        async with self.config.guild(guild).invites() as invites:
            invites.pop(code, None)

    async def _sync_guild(self, guild: discord.Guild) -> tuple[int, int, int]:
        """Sincronizza Discord -> Config. Ritorna (attivi, importati, revocati)."""
        async with self._sync_lock:
            try:
                live_invites = await guild.invites()
            except (discord.Forbidden, discord.HTTPException):
                return 0, 0, 0

            stored = await self.config.guild(guild).invites()
            live_by_code = {invite.code: invite for invite in live_invites}
            imported = 0
            revoked = 0

            for code, invite in live_by_code.items():
                data = stored.get(code)
                if data is None:
                    inviter = invite.inviter
                    data = {
                        "code": code,
                        "url": invite.url,
                        "channel_id": getattr(invite.channel, "id", None),
                        "type": "esterno",
                        "purpose": "Importato automaticamente da Discord",
                        "created_by_id": getattr(inviter, "id", None),
                        "created_by_name": str(inviter) if inviter else "Sconosciuto",
                        "created_at": invite.created_at.isoformat() if invite.created_at else self._now(),
                        "uses": invite.uses or 0,
                        "joined_users": [],
                        "last_used_by_id": None,
                        "last_used_by_name": None,
                        "last_used_at": None,
                        "revoked": False,
                        "permanent": invite.max_age == 0,
                        "managed_by_cog": False,
                    }
                    imported += 1
                else:
                    data.setdefault("joined_users", [])
                    data["url"] = invite.url
                    data["channel_id"] = getattr(invite.channel, "id", data.get("channel_id"))
                    data["uses"] = invite.uses or 0
                    data["revoked"] = False
                    data["permanent"] = invite.max_age == 0
                stored[code] = data

            for code, data in stored.items():
                data.setdefault("joined_users", [])
                if code not in live_by_code and not data.get("revoked"):
                    data["revoked"] = True
                    data["revoked_at"] = self._now()
                    data["revoked_by_id"] = None
                    revoked += 1

            await self.config.guild(guild).invites.set(stored)
            self._invite_cache[guild.id] = {
                code: invite.uses or 0 for code, invite in live_by_code.items()
            }
            return len(live_invites), imported, revoked

    @tasks.loop(minutes=5)
    async def auto_sync(self) -> None:
        for guild in self.bot.guilds:
            await self._sync_guild(guild)

    @auto_sync.before_loop
    async def before_auto_sync(self) -> None:
        await self.bot.wait_until_red_ready()

    @commands.group(name="invset", invoke_without_command=True)
    @commands.guild_only()
    async def invset(self, ctx: commands.Context) -> None:
        """Gestisce gli inviti del server senza usare il comando invite."""
        await ctx.send_help(ctx.command)

    @invset.command(name="channel", aliases=["setchannel", "canale"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invset_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Imposta il canale usato dal cog per creare i nuovi inviti."""
        if not channel.permissions_for(ctx.guild.me).create_instant_invite:
            await ctx.send("Non ho il permesso **Crea invito** in quel canale.")
            return
        await self.config.guild(ctx.guild).invite_channel_id.set(channel.id)
        await ctx.send(
            f"Canale inviti impostato su {channel.mention} (`{channel.id}`). "
            "Da ora gli inviti creati dal cog useranno sempre questo canale."
        )

    @invset.command(name="create", aliases=["crea", "new"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invset_create(
        self,
        ctx: commands.Context,
        invite_type: str,
        *,
        purpose: str,
    ) -> None:
        """Crea un invito permanente: [p]invset create <tipo> <scopo>."""
        channel_id = await self.config.guild(ctx.guild).invite_channel_id()
        if not channel_id:
            await ctx.send("Prima configura il canale inviti con `[p]invset channel ID_CANALE`.")
            return
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await ctx.send(
                "Il canale inviti configurato non esiste più. "
                "Reimpostalo con `[p]invset channel ID_CANALE`."
            )
            return
        if not channel.permissions_for(ctx.guild.me).create_instant_invite:
            await ctx.send("Non ho il permesso **Crea invito** nel canale inviti configurato.")
            return

        reason = (
            f"InviteManager: {invite_type} | {purpose} | "
            f"creato da {ctx.author} ({ctx.author.id})"
        )
        try:
            created = await channel.create_invite(
                max_age=0,
                max_uses=0,
                temporary=False,
                unique=True,
                reason=reason[:512],
            )
        except discord.Forbidden:
            await ctx.send("Non posso creare l'invito: controlla i miei permessi Discord.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"Discord ha rifiutato la creazione dell'invito: `{exc}`")
            return

        record = {
            "code": created.code,
            "url": created.url,
            "channel_id": channel.id,
            "type": invite_type,
            "purpose": purpose,
            "created_by_id": ctx.author.id,
            "created_by_name": str(ctx.author),
            "created_at": self._now(),
            "uses": created.uses or 0,
            "joined_users": [],
            "last_used_by_id": None,
            "last_used_by_name": None,
            "last_used_at": None,
            "revoked": False,
            "permanent": True,
            "managed_by_cog": True,
        }
        await self._save_record(ctx.guild, created.code, record)
        self._invite_cache.setdefault(ctx.guild.id, {})[created.code] = created.uses or 0

        embed = discord.Embed(title="Invito permanente creato", colour=discord.Colour.green())
        embed.add_field(name="Invito", value=created.url, inline=False)
        embed.add_field(name="Canale", value=channel.mention, inline=True)
        embed.add_field(name="Tipo", value=invite_type, inline=True)
        embed.add_field(name="Creatore", value=ctx.author.mention, inline=True)
        embed.add_field(name="Scopo", value=purpose, inline=False)
        embed.add_field(name="Scadenza", value="Mai", inline=True)
        embed.add_field(name="Utilizzi", value="Illimitati", inline=True)
        embed.set_footer(text=f"Codice: {created.code}")
        await ctx.send(embed=embed)

    @invset.command(name="list", aliases=["lista", "ls"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invset_list(self, ctx: commands.Context) -> None:
        """Mostra codice, creatore, scopo e numero di utilizzi degli inviti attivi."""
        await self._sync_guild(ctx.guild)
        invites = await self.config.guild(ctx.guild).invites()
        rows = []
        for code, data in sorted(
            invites.items(), key=lambda item: item[1].get("created_at", "")
        ):
            if data.get("revoked"):
                continue
            creator = data.get("created_by_name") or str(data.get("created_by_id") or "-")
            purpose = data.get("purpose", "-")
            uses = int(data.get("uses", 0) or 0)
            rows.append((code, creator, purpose, uses))

        if not rows:
            await ctx.send("Nessun invito attivo.")
            return

        header = f"{'CODICE':<11} | {'CREATORE':<18} | {'SCOPO':<34} | {'USI':>5}"
        separator = "-" * 78
        lines = []
        for code, creator, purpose, uses in rows:
            line = (
                f"{code[:11]:<11} | {creator[:18]:<18} | "
                f"{purpose[:34]:<34} | {uses:>5}"
            )
            lines.append(line)

        for index in range(0, len(lines), 15):
            block = "\n".join([header, separator, *lines[index:index + 15]])
            await ctx.send(f"```text\n{block}\n```")

    @invset.command(name="users", aliases=["usedby", "utenti", "utilizzatori"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invset_users(self, ctx: commands.Context, code: str) -> None:
        """Mostra gli utenti registrati come entrati tramite un certo invito."""
        code = self._normalize_code(code)
        data = await self._get_record(ctx.guild, code)
        if not data:
            await ctx.send("Invito non trovato.")
            return

        joined_users = data.get("joined_users", [])
        if not joined_users:
            await ctx.send(
                f"Nessun utente registrato per `{code}`. "
                "Lo storico nominativo viene raccolto dal momento in cui questa funzione è attiva."
            )
            return

        header = f"{'UTENTE':<24} | {'ID':<20} | DATA INGRESSO"
        separator = "-" * 78
        lines = []
        for entry in joined_users:
            user_id = entry.get("user_id")
            member = ctx.guild.get_member(user_id) if user_id else None
            name = str(member) if member else entry.get("user_name", "Sconosciuto")
            joined_at = entry.get("joined_at", "-")
            if joined_at != "-":
                try:
                    dt = datetime.fromisoformat(joined_at)
                    joined_at = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                except ValueError:
                    pass
            lines.append(
                f"{name[:24]:<24} | {str(user_id or '-'):<20} | {joined_at}"
            )

        for index in range(0, len(lines), 15):
            block = "\n".join([header, separator, *lines[index:index + 15]])
            await ctx.send(f"```text\n{block}\n```")

        await ctx.send(
            f"Invito `{code}`: **{len(joined_users)}** ingressi nominativi registrati / "
            f"**{int(data.get('uses', 0) or 0)}** utilizzi totali riportati da Discord."
        )

    @invset.command(name="info")
    @commands.has_guild_permissions(manage_guild=True)
    async def invset_info(self, ctx: commands.Context, code: str) -> None:
        """Mostra i dettagli di un invito."""
        code = self._normalize_code(code)
        await self._sync_guild(ctx.guild)
        data = await self._get_record(ctx.guild, code)
        if not data:
            await ctx.send("Invito non trovato.")
            return

        creator = (
            ctx.guild.get_member(data.get("created_by_id"))
            if data.get("created_by_id")
            else None
        )
        creator_value = creator.mention if creator else data.get("created_by_name", "Sconosciuto")
        channel = ctx.guild.get_channel(data.get("channel_id"))

        embed = discord.Embed(title=f"Invito {code}", colour=discord.Colour.blurple())
        embed.add_field(name="URL", value=data.get("url", f"https://discord.gg/{code}"), inline=False)
        embed.add_field(
            name="Canale",
            value=channel.mention if channel else str(data.get("channel_id", "-")),
            inline=True,
        )
        embed.add_field(name="Tipo", value=data.get("type", "-"), inline=True)
        embed.add_field(name="Creatore", value=creator_value, inline=True)
        embed.add_field(name="Scopo", value=data.get("purpose", "-"), inline=False)
        embed.add_field(name="Utilizzi", value=str(data.get("uses", 0)), inline=True)
        embed.add_field(
            name="Utenti tracciati",
            value=str(len(data.get("joined_users", []))),
            inline=True,
        )
        embed.add_field(
            name="Scadenza",
            value="Mai" if data.get("permanent") else "Non permanente",
            inline=True,
        )
        embed.add_field(
            name="Stato",
            value="Revocato" if data.get("revoked") else "Attivo",
            inline=True,
        )
        embed.add_field(
            name="Gestito dal cog",
            value="Sì" if data.get("managed_by_cog") else "Importato",
            inline=True,
        )
        if data.get("last_used_by_name"):
            embed.add_field(
                name="Ultimo utilizzo",
                value=f"{data['last_used_by_name']} ({data.get('last_used_at', '-')})",
                inline=False,
            )
        await ctx.send(embed=embed)

    @invset.command(name="edit", aliases=["modifica"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invset_edit(
        self, ctx: commands.Context, code: str, field: str, *, value: str
    ) -> None:
        """Modifica il tipo o lo scopo di un invito."""
        code = self._normalize_code(code)
        target = {
            "tipo": "type",
            "type": "type",
            "scopo": "purpose",
            "purpose": "purpose",
        }.get(field.lower().strip())
        if not target:
            await ctx.send("Campo non valido. Usa: `tipo` oppure `scopo`.")
            return

        data = await self._get_record(ctx.guild, code)
        if not data:
            await ctx.send("Invito non trovato.")
            return
        data[target] = value
        data["last_edited_at"] = self._now()
        data["last_edited_by_id"] = ctx.author.id
        await self._save_record(ctx.guild, code, data)
        await ctx.send(f"Invito `{code}` aggiornato: **{field}** = `{value}`.")

    @invset.command(name="delete", aliases=["elimina", "revoke", "revoca"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invset_delete(self, ctx: commands.Context, code: str) -> None:
        """Elimina/revoca l'invito su Discord mantenendolo nello storico interno."""
        code = self._normalize_code(code)
        data = await self._get_record(ctx.guild, code)
        if not data:
            await ctx.send("Invito non trovato.")
            return

        try:
            live = next((i for i in await ctx.guild.invites() if i.code == code), None)
            if live:
                await live.delete(
                    reason=f"InviteManager: eliminato da {ctx.author} ({ctx.author.id})"
                )
        except discord.Forbidden:
            await ctx.send(
                "Non ho il permesso **Gestisci server/inviti** per eliminare questo invito."
            )
            return
        except discord.HTTPException as exc:
            await ctx.send(f"Errore Discord durante l'eliminazione: `{exc}`")
            return

        data["revoked"] = True
        data["revoked_at"] = self._now()
        data["revoked_by_id"] = ctx.author.id
        await self._save_record(ctx.guild, code, data)
        self._invite_cache.setdefault(ctx.guild.id, {}).pop(code, None)
        await ctx.send(
            f"Invito `{code}` eliminato da Discord e segnato come revocato nello storico."
        )

    @invset.command(name="purge", aliases=["dimentica"])
    @commands.guildowner()
    async def invset_purge(self, ctx: commands.Context, code: str) -> None:
        """Cancella definitivamente anche lo storico interno di un invito."""
        code = self._normalize_code(code)
        if not await self._get_record(ctx.guild, code):
            await ctx.send("Invito non trovato.")
            return
        await self._delete_record(ctx.guild, code)
        await ctx.send(f"Record `{code}` eliminato definitivamente dall'archivio.")

    @invset.command(name="sync", aliases=["sincronizza"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invset_sync(self, ctx: commands.Context) -> None:
        """Forza la sincronizzazione immediata degli inviti Discord."""
        active, imported, revoked = await self._sync_guild(ctx.guild)
        await ctx.send(
            f"Sincronizzazione completata: **{active}** inviti attivi, "
            f"**{imported}** importati, **{revoked}** segnati come revocati."
        )

    @invset.command(name="status")
    @commands.has_guild_permissions(manage_guild=True)
    async def invset_status(self, ctx: commands.Context) -> None:
        """Mostra configurazione e stato di InviteManager."""
        channel_id = await self.config.guild(ctx.guild).invite_channel_id()
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        invites = await self.config.guild(ctx.guild).invites()
        active = sum(1 for d in invites.values() if not d.get("revoked"))
        tracked = sum(len(d.get("joined_users", [])) for d in invites.values())
        await ctx.send(
            f"**Canale inviti:** {channel.mention if channel else 'non configurato'}\n"
            f"**Inviti attivi registrati:** {active}\n"
            f"**Ingressi nominativi tracciati:** {tracked}\n"
            f"**Sync automatico:** attivo ogni 5 minuti + eventi Discord"
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        before = self._invite_cache.get(guild.id, {})
        try:
            current_invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return

        current = {i.code: i.uses or 0 for i in current_invites}
        used = next(
            (
                (i.code, i.uses or 0)
                for i in current_invites
                if (i.uses or 0) > before.get(i.code, 0)
            ),
            None,
        )
        self._invite_cache[guild.id] = current
        if not used:
            return

        data = await self._get_record(guild, used[0])
        if not data:
            await self._sync_guild(guild)
            data = await self._get_record(guild, used[0])
            if not data:
                return

        now = self._now()
        data["uses"] = used[1]
        data["last_used_by_id"] = member.id
        data["last_used_by_name"] = str(member)
        data["last_used_at"] = now
        history = data.setdefault("joined_users", [])
        history.append(
            {
                "user_id": member.id,
                "user_name": str(member),
                "joined_at": now,
            }
        )
        await self._save_record(guild, used[0], data)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if invite.guild:
            await self._sync_guild(invite.guild)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if invite.guild:
            self._invite_cache.setdefault(invite.guild.id, {}).pop(invite.code, None)
            data = await self._get_record(invite.guild, invite.code)
            if data and not data.get("revoked"):
                data["revoked"] = True
                data["revoked_at"] = self._now()
                data["revoked_by_id"] = None
                await self._save_record(invite.guild, invite.code, data)
