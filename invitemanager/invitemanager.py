from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red


VALID_ASSIGNEE_TYPES = {"persona", "ruolo", "bot", "progetto", "altro"}


class InviteManager(commands.Cog):
    """Gestione strutturata degli inviti Discord con metadati e tracciamento utilizzi."""

    __author__ = "danyx64"
    __version__ = "1.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xD15C0A11, force_registration=True)
        self.config.register_guild(invites={})
        self._invite_cache: Dict[int, Dict[str, int]] = {}

    async def cog_load(self) -> None:
        await self.bot.wait_until_red_ready()
        for guild in self.bot.guilds:
            await self._refresh_cache(guild)

    async def _refresh_cache(self, guild: discord.Guild) -> None:
        try:
            invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return
        self._invite_cache[guild.id] = {invite.code: invite.uses or 0 for invite in invites}

    async def _get_record(self, guild: discord.Guild, code: str) -> Optional[dict]:
        invites = await self.config.guild(guild).invites()
        return invites.get(code)

    async def _save_record(self, guild: discord.Guild, code: str, data: dict) -> None:
        async with self.config.guild(guild).invites() as invites:
            invites[code] = data

    async def _delete_record(self, guild: discord.Guild, code: str) -> None:
        async with self.config.guild(guild).invites() as invites:
            invites.pop(code, None)

    @commands.group(name="invite", aliases=["inviti", "invitemanager"], invoke_without_command=True)
    @commands.guild_only()
    async def invite(self, ctx: commands.Context) -> None:
        """Gestisce inviti permanenti con scopo, creatore e assegnazione."""
        await ctx.send_help(ctx.command)

    @invite.command(name="create", aliases=["crea", "new"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invite_create(self, ctx: commands.Context, channel: discord.TextChannel, invite_type: str, assignee_type: str, assignee: str, *, purpose: str) -> None:
        """Crea un invito permanente: [p]invite create #canale <tipo> <persona|ruolo|bot|progetto|altro> <assegnato> <scopo>."""
        assignee_type = assignee_type.lower().strip()
        if assignee_type not in VALID_ASSIGNEE_TYPES:
            await ctx.send(f"Tipo assegnatario non valido. Usa uno tra: {', '.join(sorted(VALID_ASSIGNEE_TYPES))}.")
            return
        if not channel.permissions_for(ctx.guild.me).create_instant_invite:
            await ctx.send("Non ho il permesso **Crea invito** in quel canale.")
            return
        reason = f"InviteManager: {invite_type} | {purpose} | creato da {ctx.author} ({ctx.author.id})"
        try:
            created = await channel.create_invite(max_age=0, max_uses=0, temporary=False, unique=True, reason=reason[:512])
        except discord.Forbidden:
            await ctx.send("Non posso creare l'invito: controlla i miei permessi Discord.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"Discord ha rifiutato la creazione dell'invito: `{exc}`")
            return
        record = {"code": created.code, "url": created.url, "channel_id": channel.id, "type": invite_type, "purpose": purpose, "created_by_id": ctx.author.id, "created_by_name": str(ctx.author), "assigned_type": assignee_type, "assigned_to": assignee, "created_at": datetime.now(timezone.utc).isoformat(), "uses": created.uses or 0, "last_used_by_id": None, "last_used_by_name": None, "last_used_at": None, "revoked": False, "permanent": True}
        await self._save_record(ctx.guild, created.code, record)
        self._invite_cache.setdefault(ctx.guild.id, {})[created.code] = created.uses or 0
        embed = discord.Embed(title="Invito creato", colour=discord.Colour.green())
        embed.add_field(name="Invito", value=created.url, inline=False)
        embed.add_field(name="Tipo", value=invite_type, inline=True)
        embed.add_field(name="Scopo", value=purpose, inline=False)
        embed.add_field(name="Creatore", value=ctx.author.mention, inline=True)
        embed.add_field(name="Assegnato", value=f"{assignee_type}: {assignee}", inline=True)
        embed.add_field(name="Scadenza", value="Mai", inline=True)
        embed.add_field(name="Limite utilizzi", value="Nessuno", inline=True)
        embed.set_footer(text=f"Codice: {created.code}")
        await ctx.send(embed=embed)

    @invite.command(name="list", aliases=["lista", "ls"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invite_list(self, ctx: commands.Context, include_revoked: bool = False) -> None:
        """Mostra gli inviti gestiti dal cog."""
        invites = await self.config.guild(ctx.guild).invites()
        rows = []
        for code, data in invites.items():
            if data.get("revoked") and not include_revoked:
                continue
            status = "revocato" if data.get("revoked") else "attivo"
            rows.append(f"`{code}` • **{data.get('type', '-')}** • {data.get('assigned_type', '-')}: {data.get('assigned_to', '-')} • usi: **{data.get('uses', 0)}** • {status}")
        if not rows:
            await ctx.send("Nessun invito gestito dal cog.")
            return
        embed = discord.Embed(title="Inviti gestiti", colour=discord.Colour.blurple())
        for index in range(0, len(rows), 10):
            embed.add_field(name=f"Inviti {index + 1}-{min(index + 10, len(rows))}", value="\n".join(rows[index:index + 10]), inline=False)
        await ctx.send(embed=embed)

    @invite.command(name="info")
    @commands.has_guild_permissions(manage_guild=True)
    async def invite_info(self, ctx: commands.Context, code: str) -> None:
        """Mostra tutti i metadati di un invito gestito."""
        code = code.rsplit("/", 1)[-1].strip()
        data = await self._get_record(ctx.guild, code)
        if not data:
            await ctx.send("Invito non trovato nell'archivio del cog.")
            return
        creator = ctx.guild.get_member(data.get("created_by_id"))
        creator_value = creator.mention if creator else data.get("created_by_name", str(data.get("created_by_id")))
        embed = discord.Embed(title=f"Invito {code}", colour=discord.Colour.blurple())
        embed.add_field(name="URL", value=data.get("url", f"https://discord.gg/{code}"), inline=False)
        embed.add_field(name="Tipo", value=data.get("type", "-"), inline=True)
        embed.add_field(name="Scopo", value=data.get("purpose", "-"), inline=False)
        embed.add_field(name="Creatore", value=creator_value, inline=True)
        embed.add_field(name="Assegnato", value=f"{data.get('assigned_type', '-')}: {data.get('assigned_to', '-')}", inline=True)
        embed.add_field(name="Utilizzi", value=str(data.get("uses", 0)), inline=True)
        embed.add_field(name="Scadenza", value="Mai", inline=True)
        embed.add_field(name="Stato", value="Revocato" if data.get("revoked") else "Attivo", inline=True)
        if data.get("last_used_by_name"):
            embed.add_field(name="Ultimo utilizzo", value=f"{data['last_used_by_name']} ({data.get('last_used_at', '-')})", inline=False)
        await ctx.send(embed=embed)

    @invite.command(name="edit", aliases=["modifica"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invite_edit(self, ctx: commands.Context, code: str, field: str, *, value: str) -> None:
        """Modifica tipo, scopo, tipo assegnatario o assegnatario."""
        code = code.rsplit("/", 1)[-1].strip()
        target = {"tipo": "type", "type": "type", "scopo": "purpose", "purpose": "purpose", "assegnato": "assigned_to", "assigned": "assigned_to", "assegnato_tipo": "assigned_type", "assigned_type": "assigned_type"}.get(field.lower().strip())
        if not target:
            await ctx.send("Campo non valido. Usa: `tipo`, `scopo`, `assegnato`, `assegnato_tipo`.")
            return
        if target == "assigned_type" and value.lower() not in VALID_ASSIGNEE_TYPES:
            await ctx.send("Tipo assegnatario non valido.")
            return
        data = await self._get_record(ctx.guild, code)
        if not data:
            await ctx.send("Invito non trovato nell'archivio del cog.")
            return
        data[target] = value.lower() if target == "assigned_type" else value
        await self._save_record(ctx.guild, code, data)
        await ctx.tick()

    @invite.command(name="revoke", aliases=["revoca", "delete"])
    @commands.has_guild_permissions(manage_guild=True)
    async def invite_revoke(self, ctx: commands.Context, code: str) -> None:
        """Revoca un invito Discord ma conserva i metadati nello storico."""
        code = code.rsplit("/", 1)[-1].strip()
        data = await self._get_record(ctx.guild, code)
        if not data:
            await ctx.send("Invito non trovato nell'archivio del cog.")
            return
        try:
            live = next((i for i in await ctx.guild.invites() if i.code == code), None)
            if live:
                await live.delete(reason=f"InviteManager: revocato da {ctx.author} ({ctx.author.id})")
        except discord.Forbidden:
            await ctx.send("Non ho il permesso per revocare questo invito.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"Errore Discord durante la revoca: `{exc}`")
            return
        data["revoked"] = True
        data["revoked_at"] = datetime.now(timezone.utc).isoformat()
        data["revoked_by_id"] = ctx.author.id
        await self._save_record(ctx.guild, code, data)
        self._invite_cache.setdefault(ctx.guild.id, {}).pop(code, None)
        await ctx.send(f"Invito `{code}` revocato. I metadati restano nello storico.")

    @invite.command(name="purge", aliases=["dimentica"])
    @commands.guildowner()
    async def invite_purge(self, ctx: commands.Context, code: str) -> None:
        """Rimuove definitivamente un record dall'archivio del cog."""
        code = code.rsplit("/", 1)[-1].strip()
        if not await self._get_record(ctx.guild, code):
            await ctx.send("Invito non trovato nell'archivio del cog.")
            return
        await self._delete_record(ctx.guild, code)
        await ctx.tick()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        before = self._invite_cache.get(guild.id, {})
        try:
            current_invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return
        current = {i.code: i.uses or 0 for i in current_invites}
        used = next(((i.code, i.uses or 0) for i in current_invites if (i.uses or 0) > before.get(i.code, 0)), None)
        self._invite_cache[guild.id] = current
        if not used:
            return
        data = await self._get_record(guild, used[0])
        if not data:
            return
        data["uses"] = used[1]
        data["last_used_by_id"] = member.id
        data["last_used_by_name"] = str(member)
        data["last_used_at"] = datetime.now(timezone.utc).isoformat()
        await self._save_record(guild, used[0], data)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if invite.guild:
            self._invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if invite.guild:
            self._invite_cache.setdefault(invite.guild.id, {}).pop(invite.code, None)
            data = await self._get_record(invite.guild, invite.code)
            if data and not data.get("revoked"):
                data["revoked"] = True
                data["revoked_at"] = datetime.now(timezone.utc).isoformat()
                data["revoked_by_id"] = None
                await self._save_record(invite.guild, invite.code, data)
