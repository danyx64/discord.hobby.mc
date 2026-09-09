from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, Optional

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red


VALID_ASSIGNEE_TYPES = {"utente", "ruolo", "bot", "progetto", "altro"}


class InviteManager(commands.Cog):
    """Gestione centralizzata e sincronizzata degli inviti Discord."""

    __author__ = "danyx64"
    __version__ = "1.1.0"

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
                        "assigned_type": "altro",
                        "assigned_to": "non assegnato",
                        "created_at": invite.created_at.isoformat() if invite.created_at else self._now(),
                        "uses": invite.uses or 0,
                        "last_used_by_id": None,
                        "last_used_by_name": None,
                        "last_used_at": None,
                        "revoked": False,
                        "permanent": invite.max_age == 0,
                        "managed_by_cog": False,
                    }
                    imported += 1
                else:
                    data["url"] = invite.url
                    data["channel_id"] = getattr(invite.channel, "id", data.get("channel_id"))
                    data["uses"] = invite.uses or 0
                    data["revoked"] = False
                    data["permanent"] = invite.max_age == 0
                stored[code] = data

            for code, data in stored.items():
                if code not in live_by_code and not data.get("revoked"):
                    data["revoked"] = True
                    data["revoked_at"] = self._now()
                    data["revoked_by_id"] = None
                    revoked += 1

            await self.config.guild(guild).invites.set(stored)
            self._invite_cache[guild.id] = {code: invite.uses or 0 for code, invite in live_by_code.items()}
            return len(live_invites), imported, revoked

    @tasks.loop(minutes=5)
    async def auto_sync(self) -> None:
        for guild in self.bot.guilds:
            await self._sync_guild(guild)

    @auto_sync.before_loop
    async def before_auto_sync(self) -> None:
        await self.bot.wait_until_red_ready()

    @commands.group(name="invite", aliases=["inviti", "invitemanager"], invoke_without_command=True)
    @commands.guild_only()
    async def invite(self, ctx: commands.Context) -> None:
        """Gestisce gli inviti del server."""
        await ctx.send_help(ctx.command)

    @invite.command(name="channel", aliases=["setchannel", "canale"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invite_channel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Imposta il canale in cui InviteManager deve creare tutti i nuovi inviti.

        Esempio: [p]invite channel 123456789012345678
        """
        if not channel.permissions_for(ctx.guild.me).create_instant_invite:
            await ctx.send("Non ho il permesso **Crea invito** in quel canale.")
            return
        await self.config.guild(ctx.guild).invite_channel_id.set(channel.id)
        await ctx.send(f"Canale inviti impostato su {channel.mention} (`{channel.id}`). Da ora gli inviti creati dal cog useranno sempre questo canale.")

    @invite.command(name="create", aliases=["crea", "new"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invite_create(self, ctx: commands.Context, invite_type: str, assignee_type: str, assignee: str, *, purpose: str) -> None:
        """Crea un invito permanente nel canale configurato.

        Sintassi: [p]invite create <tipo> <utente|ruolo|bot|progetto|altro> <assegnato> <scopo>
        """
        assignee_type = assignee_type.lower().strip()
        if assignee_type == "persona":
            assignee_type = "utente"
        if assignee_type not in VALID_ASSIGNEE_TYPES:
            await ctx.send(f"Tipo assegnatario non valido. Usa uno tra: {', '.join(sorted(VALID_ASSIGNEE_TYPES))}.")
            return

        channel_id = await self.config.guild(ctx.guild).invite_channel_id()
        if not channel_id:
            await ctx.send("Prima configura il canale inviti con `[p]invite channel ID_CANALE`.")
            return
        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await ctx.send("Il canale inviti configurato non esiste più. Reimpostalo con `[p]invite channel ID_CANALE`.")
            return
        if not channel.permissions_for(ctx.guild.me).create_instant_invite:
            await ctx.send("Non ho il permesso **Crea invito** nel canale inviti configurato.")
            return

        reason = f"InviteManager: {invite_type} | {purpose} | creato da {ctx.author} ({ctx.author.id})"
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
            "assigned_type": assignee_type,
            "assigned_to": assignee,
            "created_at": self._now(),
            "uses": created.uses or 0,
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
        embed.add_field(name="Assegnato", value=f"{assignee_type}: {assignee}", inline=False)
        embed.add_field(name="Scadenza", value="Mai", inline=True)
        embed.add_field(name="Utilizzi", value="Illimitati", inline=True)
        embed.set_footer(text=f"Codice: {created.code}")
        await ctx.send(embed=embed)

    @invite.command(name="list", aliases=["lista", "ls"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invite_list(self, ctx: commands.Context) -> None:
        """Mostra gli inviti attivi in formato tabella."""
        await self._sync_guild(ctx.guild)
        invites = await self.config.guild(ctx.guild).invites()
        rows = []
        for code, data in sorted(invites.items(), key=lambda item: item[1].get("created_at", "")):
            if data.get("revoked"):
                continue
            creator = data.get("created_by_name") or str(data.get("created_by_id") or "-")
            purpose = data.get("purpose", "-")
            assigned = f"{data.get('assigned_type', '-')}: {data.get('assigned_to', '-')}"
            rows.append((code, creator, purpose, assigned))

        if not rows:
            await ctx.send("Nessun invito attivo.")
            return

        header = f"{'CODICE':<11} | {'CREATORE':<18} | {'SCOPO':<28} | ASSEGNATO A"
        separator = "-" * 90
        chunks = []
        for code, creator, purpose, assigned in rows:
            creator = creator[:18]
            purpose = purpose[:28]
            assigned = assigned[:28]
            line = f"{code[:11]:<11} | {creator:<18} | {purpose:<28} | {assigned}"
            chunks.append(line)

        for index in range(0, len(chunks), 15):
            block = "\n".join([header, separator, *chunks[index:index + 15]])
            await ctx.send(f"```text\n{block}\n```")

    @invite.command(name="info")
    @commands.has_guild_permissions(manage_guild=True)
    async def invite_info(self, ctx: commands.Context, code: str) -> None:
        """Mostra i dettagli di un invito."""
        code = self._normalize_code(code)
        await self._sync_guild(ctx.guild)
        data = await self._get_record(ctx.guild, code)
        if not data:
            await ctx.send("Invito non trovato.")
            return

        creator = ctx.guild.get_member(data.get("created_by_id")) if data.get("created_by_id") else None
        creator_value = creator.mention if creator else data.get("created_by_name", "Sconosciuto")
        channel = ctx.guild.get_channel(data.get("channel_id"))

        embed = discord.Embed(title=f"Invito {code}", colour=discord.Colour.blurple())
        embed.add_field(name="URL", value=data.get("url", f"https://discord.gg/{code}"), inline=False)
        embed.add_field(name="Canale", value=channel.mention if channel else str(data.get("channel_id", "-")), inline=True)
        embed.add_field(name="Tipo", value=data.get("type", "-"), inline=True)
        embed.add_field(name="Creatore", value=creator_value, inline=True)
        embed.add_field(name="Scopo", value=data.get("purpose", "-"), inline=False)
        embed.add_field(name="Assegnato", value=f"{data.get('assigned_type', '-')}: {data.get('assigned_to', '-')}", inline=False)
        embed.add_field(name="Utilizzi", value=str(data.get("uses", 0)), inline=True)
        embed.add_field(name="Scadenza", value="Mai" if data.get("permanent") else "Non permanente", inline=True)
        embed.add_field(name="Stato", value="Revocato" if data.get("revoked") else "Attivo", inline=True)
        embed.add_field(name="Gestito dal cog", value="Sì" if data.get("managed_by_cog") else "Importato", inline=True)
        if data.get("last_used_by_name"):
            embed.add_field(name="Ultimo utilizzo", value=f"{data['last_used_by_name']} ({data.get('last_used_at', '-')})", inline=False)
        await ctx.send(embed=embed)

    @invite.command(name="edit", aliases=["modifica"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invite_edit(self, ctx: commands.Context, code: str, field: str, *, value: str) -> None:
        """Modifica tipo, scopo, assegnatario o tipo assegnatario.

        Esempio: [p]invite edit ABC123 scopo Accesso bot backup
        """
        code = self._normalize_code(code)
        target = {
            "tipo": "type",
            "type": "type",
            "scopo": "purpose",
            "purpose": "purpose",
            "assegnato": "assigned_to",
            "assigned": "assigned_to",
            "assegnato_tipo": "assigned_type",
            "assigned_type": "assigned_type",
        }.get(field.lower().strip())
        if not target:
            await ctx.send("Campo non valido. Usa: `tipo`, `scopo`, `assegnato`, `assegnato_tipo`.")
            return
        if target == "assigned_type":
            value = value.lower().strip()
            if value == "persona":
                value = "utente"
            if value not in VALID_ASSIGNEE_TYPES:
                await ctx.send(f"Tipo assegnatario non valido. Usa: {', '.join(sorted(VALID_ASSIGNEE_TYPES))}.")
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

    @invite.command(name="delete", aliases=["elimina", "revoke", "revoca"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invite_delete(self, ctx: commands.Context, code: str) -> None:
        """Elimina/revoca l'invito su Discord mantenendolo nello storico interno."""
        code = self._normalize_code(code)
        data = await self._get_record(ctx.guild, code)
        if not data:
            await ctx.send("Invito non trovato.")
            return

        try:
            live = next((i for i in await ctx.guild.invites() if i.code == code), None)
            if live:
                await live.delete(reason=f"InviteManager: eliminato da {ctx.author} ({ctx.author.id})")
        except discord.Forbidden:
            await ctx.send("Non ho il permesso **Gestisci server/inviti** per eliminare questo invito.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"Errore Discord durante l'eliminazione: `{exc}`")
            return

        data["revoked"] = True
        data["revoked_at"] = self._now()
        data["revoked_by_id"] = ctx.author.id
        await self._save_record(ctx.guild, code, data)
        self._invite_cache.setdefault(ctx.guild.id, {}).pop(code, None)
        await ctx.send(f"Invito `{code}` eliminato da Discord e segnato come revocato nello storico.")

    @invite.command(name="purge", aliases=["dimentica"])
    @commands.guildowner()
    async def invite_purge(self, ctx: commands.Context, code: str) -> None:
        """Cancella definitivamente anche lo storico interno di un invito."""
        code = self._normalize_code(code)
        if not await self._get_record(ctx.guild, code):
            await ctx.send("Invito non trovato.")
            return
        await self._delete_record(ctx.guild, code)
        await ctx.send(f"Record `{code}` eliminato definitivamente dall'archivio.")

    @invite.command(name="sync", aliases=["sincronizza"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invite_sync(self, ctx: commands.Context) -> None:
        """Forza la sincronizzazione immediata degli inviti Discord."""
        active, imported, revoked = await self._sync_guild(ctx.guild)
        await ctx.send(
            f"Sincronizzazione completata: **{active}** inviti attivi, "
            f"**{imported}** importati, **{revoked}** segnati come revocati."
        )

    @invite.command(name="status")
    @commands.has_guild_permissions(manage_guild=True)
    async def invite_status(self, ctx: commands.Context) -> None:
        """Mostra configurazione e stato di InviteManager."""
        channel_id = await self.config.guild(ctx.guild).invite_channel_id()
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        invites = await self.config.guild(ctx.guild).invites()
        active = sum(1 for d in invites.values() if not d.get("revoked"))
        await ctx.send(
            f"**Canale inviti:** {channel.mention if channel else 'non configurato'}\n"
            f"**Inviti attivi registrati:** {active}\n"
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
            ((i.code, i.uses or 0) for i in current_invites if (i.uses or 0) > before.get(i.code, 0)),
            None,
        )
        self._invite_cache[guild.id] = current
        if not used:
            return

        data = await self._get_record(guild, used[0])
        if data:
            data["uses"] = used[1]
            data["last_used_by_id"] = member.id
            data["last_used_by_name"] = str(member)
            data["last_used_at"] = self._now()
            await self._save_record(guild, used[0], data)
        else:
            await self._sync_guild(guild)

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
