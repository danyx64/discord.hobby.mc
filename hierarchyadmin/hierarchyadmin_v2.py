import discord
from redbot.core import commands

from .hierarchyadmin import HierarchyAdmin as BaseHierarchyAdmin


class HierarchyAdmin(BaseHierarchyAdmin):
    """HierarchyAdmin v1.1: diagnostica permessi effettivi per canale."""

    __version__ = "1.1.0"

    @staticmethod
    def _state(value):
        if value is True:
            return "✅ allow"
        if value is False:
            return "❌ deny"
        return "➖ inherit"

    @staticmethod
    def _overwrite_summary(overwrite: discord.PermissionOverwrite):
        entries = []
        for name, value in overwrite:
            if value is not None:
                entries.append(f"`{name}`: {'✅ allow' if value else '❌ deny'}")
        return entries

    @BaseHierarchyAdmin.ha.command(name="check", aliases=["diagnose", "diagnostic"])
    @commands.admin_or_permissions(manage_roles=True)
    async def ha_check(self, ctx: commands.Context, user_id: int, channel_id: int):
        """Diagnostica i permessi effettivi di un membro in uno specifico canale."""
        member = await self._member(ctx, user_id)
        if member is None:
            return
        channel = await self._channel(ctx, channel_id)
        if channel is None:
            return

        effective = channel.permissions_for(member)
        important = (
            "administrator",
            "view_channel",
            "read_message_history",
            "send_messages",
            "manage_messages",
            "manage_channels",
            "manage_threads",
            "create_public_threads",
            "create_private_threads",
            "send_messages_in_threads",
        )

        lines = [
            f"**Utente:** {member.mention} (`{member.id}`)",
            f"**Canale:** {channel.mention if hasattr(channel, 'mention') else channel.name} (`{channel.id}`)",
            f"**Ruolo più alto:** {member.top_role.mention}",
            "",
            "**Permessi effettivi nel canale:**",
        ]
        for permission in important:
            if hasattr(effective, permission):
                value = getattr(effective, permission)
                lines.append(f"{'✅' if value else '❌'} `{permission}`")

        if effective.administrator:
            lines.append("")
            lines.append("**Nota:** `administrator` è attivo; gli override normali del canale non dovrebbero bloccare questi permessi.")

        roles = [role for role in member.roles if not role.is_default()]
        lines.append("")
        lines.append("**Ruoli del membro:** " + (", ".join(role.mention for role in reversed(roles)) if roles else "Nessuno"))

        overwrite_sections = []
        everyone_overwrite = channel.overwrites_for(ctx.guild.default_role)
        everyone_entries = self._overwrite_summary(everyone_overwrite)
        if everyone_entries:
            overwrite_sections.append(("@everyone", everyone_entries))

        for role in roles:
            overwrite = channel.overwrites_for(role)
            entries = self._overwrite_summary(overwrite)
            if entries:
                overwrite_sections.append((role.name, entries))

        member_overwrite = channel.overwrites_for(member)
        member_entries = self._overwrite_summary(member_overwrite)
        if member_entries:
            overwrite_sections.append((f"Utente {member.display_name}", member_entries))

        if overwrite_sections:
            lines.append("")
            lines.append("**Override presenti:**")
            for title, entries in overwrite_sections:
                lines.append(f"**{title}:**")
                lines.extend(entries)
        else:
            lines.append("")
            lines.append("**Override presenti:** nessuno per @everyone, ruoli o utente.")

        # Diagnostica mirata al problema piu comune: eliminazione messaggi.
        lines.append("")
        if effective.manage_messages:
            lines.append("**Diagnosi Gestisci messaggi:** ✅ Discord calcola `manage_messages` come attivo in questo canale.")
            if effective.administrator:
                lines.append("Se il client non mostra comunque Elimina messaggio, il blocco non deriva dai normali permessi/override del canale.")
        else:
            lines.append("**Diagnosi Gestisci messaggi:** ❌ `manage_messages` non è effettivo in questo canale; controlla gli override sopra.")

        # Discord limita gli embed a 4096 caratteri; spezza in piu pagine se serve.
        pages = []
        current = ""
        for line in lines:
            candidate = current + ("\n" if current else "") + line
            if len(candidate) > 3900:
                pages.append(current)
                current = line
            else:
                current = candidate
        if current:
            pages.append(current)

        for index, page in enumerate(pages, 1):
            embed = discord.Embed(
                title=f"Diagnostica permessi - pagina {index}/{len(pages)}",
                description=page,
                colour=discord.Colour.blurple(),
            )
            await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
