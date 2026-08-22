import discord
from discord import app_commands
from redbot.core import commands


# Compatibilita' con versioni di discord.py che non espongono ancora questi decorator.
def _identity_decorator(**kwargs):
    def deco(obj):
        return obj
    return deco


allowed_installs = getattr(app_commands, "allowed_installs", _identity_decorator)
allowed_contexts = getattr(app_commands, "allowed_contexts", _identity_decorator)


class UserInstallControl(commands.Cog):
    """Comandi slash pensati anche per installazioni utente dell'app Discord."""

    def __init__(self, bot):
        self.bot = bot

    async def red_delete_data_for_user(self, **kwargs):
        return

    userapp = app_commands.Group(
        name="userapp",
        description="Comandi dell'app installabile sul tuo account Discord",
    )

    async def _is_owner(self, interaction: discord.Interaction) -> bool:
        return await self.bot.is_owner(interaction.user)

    @userapp.command(name="ping", description="Controlla se l'app e' attiva")
    @allowed_installs(guilds=True, users=True)
    @allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        where = "DM / installazione utente" if interaction.guild is None else interaction.guild.name
        await interaction.response.send_message(
            f"✅ App attiva. Latenza: **{latency} ms**\nContesto: **{where}**",
            ephemeral=True,
        )

    @userapp.command(name="info", description="Mostra informazioni sull'installazione e sul contesto")
    @allowed_installs(guilds=True, users=True)
    @allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def info(self, interaction: discord.Interaction):
        embed = discord.Embed(title="User Install", colour=discord.Colour.blurple())
        embed.add_field(name="Utente", value=f"{interaction.user} (`{interaction.user.id}`)", inline=False)
        if interaction.guild:
            embed.add_field(name="Server", value=f"{interaction.guild.name} (`{interaction.guild.id}`)", inline=False)
        else:
            embed.add_field(name="Contesto", value="DM / installazione utente", inline=False)
        embed.add_field(
            name="Nota",
            value=(
                "Discord non fornisce al bot una lista generale degli account che hanno installato l'app. "
                "Il bot puo' conoscere l'utente quando questo esegue un comando o interagisce con l'app."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @userapp.command(name="remove", description="Spiega come rimuovere l'app dal proprio account")
    @allowed_installs(guilds=True, users=True)
    @allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def remove(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Per rimuovere l'app dal tuo account Discord, apri le impostazioni di Discord e rimuovi/revoca l'app dalle app autorizzate o dalle integrazioni del tuo account. "
            "L'app non puo' revocare da sola l'installazione di un altro utente.",
            ephemeral=True,
        )

    @userapp.command(name="ownerstats", description="Statistiche globali del bot, solo proprietario")
    @allowed_installs(guilds=True, users=True)
    @allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def ownerstats(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction):
            return await interaction.response.send_message("Comando riservato al proprietario del bot.", ephemeral=True)

        users = set()
        for guild in self.bot.guilds:
            users.update(member.id for member in guild.members)

        await interaction.response.send_message(
            f"**Server del bot:** {len(self.bot.guilds)}\n"
            f"**Utenti visibili nelle cache dei server:** {len(users)}\n"
            "**Installazioni utente totali:** non disponibili tramite una lista API generale.",
            ephemeral=True,
        )

    @commands.command(name="userinstallsync")
    @commands.is_owner()
    async def userinstallsync(self, ctx: commands.Context):
        """Sincronizza globalmente gli slash command del cog."""
        try:
            synced = await self.bot.tree.sync()
        except Exception as exc:
            return await ctx.send(f"Errore durante la sincronizzazione: `{exc}`")
        await ctx.send(f"Sincronizzazione globale completata: **{len(synced)}** comandi.")
