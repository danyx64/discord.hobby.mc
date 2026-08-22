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


def user_install_command(func):
    """Abilita il comando sia per Guild Install sia per User Install, anche in DM."""
    func = allowed_installs(guilds=True, users=True)(func)
    func = allowed_contexts(guilds=True, dms=True, private_channels=True)(func)
    return func


class UserInstallControl(commands.Cog):
    """Comandi per User Install che si adattano al contesto e ai permessi disponibili."""

    def __init__(self, bot):
        self.bot = bot

    async def red_delete_data_for_user(self, **kwargs):
        # Il cog non mantiene un database degli utenti che usano l'app.
        return

    userapp = app_commands.Group(
        name="userapp",
        description="Controlli e utility dell'app installata sul tuo account",
    )

    async def _is_owner(self, interaction: discord.Interaction) -> bool:
        return await self.bot.is_owner(interaction.user)

    async def _respond(self, interaction: discord.Interaction, content=None, *, embed=None, ephemeral=True):
        if interaction.response.is_done():
            return await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
        return await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)

    def _bot_member(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return None
        return guild.me

    @userapp.command(name="ping", description="Controlla se l'app e' attiva")
    @user_install_command
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        where = "DM / User Install" if interaction.guild is None else interaction.guild.name
        await self._respond(
            interaction,
            f"✅ App attiva. Latenza: **{latency} ms**\nContesto: **{where}**",
        )

    @userapp.command(name="me", description="Mostra le informazioni Discord che l'app vede su di te")
    @user_install_command
    async def me(self, interaction: discord.Interaction):
        user = interaction.user
        embed = discord.Embed(title="Il tuo profilo", colour=discord.Colour.blurple())
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Nome", value=str(user), inline=True)
        embed.add_field(name="ID", value=f"`{user.id}`", inline=True)
        embed.add_field(name="Creato", value=f"<t:{int(user.created_at.timestamp())}:F>", inline=False)
        if isinstance(user, discord.Member):
            embed.add_field(name="Display name", value=user.display_name, inline=True)
            embed.add_field(name="Ruoli visibili", value=str(max(0, len(user.roles) - 1)), inline=True)
        await self._respond(interaction, embed=embed)

    @userapp.command(name="avatar", description="Mostra il tuo avatar in alta qualita'")
    @user_install_command
    async def avatar(self, interaction: discord.Interaction):
        user = interaction.user
        embed = discord.Embed(title=f"Avatar di {user}", colour=discord.Colour.blurple())
        embed.set_image(url=user.display_avatar.replace(size=4096).url)
        await self._respond(interaction, embed=embed)

    @userapp.command(name="dmme", description="Fa tentare al bot di inviarti un DM normale")
    @app_commands.describe(message="Testo da inviarti in DM")
    @user_install_command
    async def dmme(self, interaction: discord.Interaction, message: str = "Ciao! Questo DM e' stato inviato dal bot."):
        if len(message) > 1900:
            return await self._respond(interaction, "Il messaggio e' troppo lungo. Massimo 1900 caratteri.")
        try:
            await interaction.user.send(message)
        except discord.Forbidden:
            return await self._respond(
                interaction,
                "❌ Discord non mi permette di aprire/inviare un DM a questo account in questo momento.",
            )
        except discord.HTTPException as exc:
            return await self._respond(interaction, f"❌ Errore Discord durante il DM: `{exc}`")
        await self._respond(interaction, "✅ DM inviato.")

    @userapp.command(name="context", description="Mostra cosa l'app puo' vedere nel contesto corrente")
    @user_install_command
    async def context(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Contesto User Install", colour=discord.Colour.blurple())
        embed.add_field(name="Utente", value=f"{interaction.user} (`{interaction.user.id}`)", inline=False)
        if interaction.guild is None:
            embed.add_field(name="Tipo", value="DM / contesto privato", inline=False)
            embed.add_field(
                name="Disponibile",
                value="Risposte slash, follow-up dell'interazione, utility profilo e tentativo DM.",
                inline=False,
            )
        else:
            embed.add_field(name="Server", value=f"{interaction.guild.name} (`{interaction.guild.id}`)", inline=False)
            channel = interaction.channel
            if channel is not None:
                embed.add_field(name="Canale", value=f"{getattr(channel, 'name', 'sconosciuto')} (`{channel.id}`)", inline=False)
            me = self._bot_member(interaction)
            if me is None:
                embed.add_field(
                    name="Bot nel server",
                    value="No. Il comando funziona come User Install, ma non posso amministrare il server.",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Bot nel server",
                    value="Si. Posso usare anche i permessi che il bot possiede qui.",
                    inline=False,
                )
        await self._respond(interaction, embed=embed)

    @userapp.command(name="permissions", description="Mostra i permessi effettivi del bot nel server corrente")
    @user_install_command
    async def permissions(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await self._respond(interaction, "Questo comando richiede un contesto server.")
        me = self._bot_member(interaction)
        if me is None:
            return await self._respond(
                interaction,
                "Il bot non e' membro di questo server: la User Install non concede permessi amministrativi del server.",
            )

        perms = me.guild_permissions
        important = [
            ("Administrator", perms.administrator),
            ("Manage Guild", perms.manage_guild),
            ("Manage Channels", perms.manage_channels),
            ("Manage Roles", perms.manage_roles),
            ("Manage Messages", perms.manage_messages),
            ("Kick Members", perms.kick_members),
            ("Ban Members", perms.ban_members),
            ("Moderate Members", perms.moderate_members),
            ("Create Invites", perms.create_instant_invite),
            ("Send Messages", perms.send_messages),
        ]
        text = "\n".join(f"{'✅' if value else '❌'} {name}" for name, value in important)
        embed = discord.Embed(title=f"Permessi in {interaction.guild.name}", description=text, colour=discord.Colour.blurple())
        embed.set_footer(text=f"Bitfield: {perms.value}")
        await self._respond(interaction, embed=embed)

    @userapp.command(name="server", description="Mostra info sul server se disponibili nel contesto")
    @user_install_command
    async def server(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return await self._respond(interaction, "Questo comando richiede un contesto server.")

        embed = discord.Embed(title=guild.name, colour=discord.Colour.blurple())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="ID", value=f"`{guild.id}`", inline=True)
        embed.add_field(name="Membri", value=str(guild.member_count or "non disponibile"), inline=True)
        embed.add_field(name="Canali visibili/cache", value=str(len(guild.channels)), inline=True)
        me = self._bot_member(interaction)
        embed.add_field(name="Bot membro", value="Si" if me else "No / solo User Install", inline=True)
        await self._respond(interaction, embed=embed)

    @userapp.command(name="channels", description="Elenca i canali che il bot puo' vedere nel server corrente")
    @user_install_command
    async def channels(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return await self._respond(interaction, "Questo comando richiede un contesto server.")
        me = self._bot_member(interaction)
        if me is None:
            return await self._respond(interaction, "Il bot non e' membro di questo server, quindi non puo' enumerarne i canali.")

        lines = []
        for channel in guild.channels:
            try:
                if not channel.permissions_for(me).view_channel:
                    continue
            except Exception:
                continue
            kind = channel.__class__.__name__.replace("Channel", "")
            lines.append(f"`{channel.id}` — **{kind}** — {getattr(channel, 'name', 'senza nome')}")

        if not lines:
            return await self._respond(interaction, "Nessun canale visibile al bot.")
        text = "\n".join(lines[:50])
        if len(lines) > 50:
            text += f"\n… e altri {len(lines) - 50}."
        await self._respond(interaction, text)

    @userapp.command(name="remove", description="Spiega come rimuovere l'app dal proprio account")
    @user_install_command
    async def remove(self, interaction: discord.Interaction):
        await self._respond(
            interaction,
            "Per scollegare la User Install devi rimuovere/revocare l'app dalle impostazioni Discord. "
            "Discord non permette all'app di disinstallarsi autonomamente dall'account di un'altra persona.",
        )

    @userapp.command(name="ownerstats", description="Statistiche globali del bot, solo proprietario")
    @user_install_command
    async def ownerstats(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction):
            return await self._respond(interaction, "Comando riservato al proprietario del bot.")

        users = set()
        for guild in self.bot.guilds:
            users.update(member.id for member in guild.members)

        await self._respond(
            interaction,
            f"**Server del bot:** {len(self.bot.guilds)}\n"
            f"**Utenti visibili nelle cache dei server:** {len(users)}\n"
            "**Installazioni utente totali:** Discord non espone una lista generale al bot.\n"
            "**Registro installatori:** non mantenuto da questo cog.",
        )

    @userapp.command(name="ownerdm", description="Invia un singolo DM a un ID utente, solo proprietario")
    @app_commands.describe(user_id="ID Discord dell'utente", message="Messaggio da inviare")
    @user_install_command
    async def ownerdm(self, interaction: discord.Interaction, user_id: str, message: str):
        if not await self._is_owner(interaction):
            return await self._respond(interaction, "Comando riservato al proprietario del bot.")
        if len(message) > 1900:
            return await self._respond(interaction, "Il messaggio e' troppo lungo. Massimo 1900 caratteri.")
        try:
            uid = int(user_id)
        except ValueError:
            return await self._respond(interaction, "ID utente non valido.")

        user = self.bot.get_user(uid)
        if user is None:
            try:
                user = await self.bot.fetch_user(uid)
            except (discord.NotFound, discord.HTTPException):
                return await self._respond(interaction, "Utente non trovato o non recuperabile da Discord.")

        try:
            await user.send(message)
        except discord.Forbidden:
            return await self._respond(
                interaction,
                "Discord ha bloccato il DM. Una User Install non garantisce automaticamente il permesso di inviare DM normali.",
            )
        except discord.HTTPException as exc:
            return await self._respond(interaction, f"Errore Discord durante il DM: `{exc}`")
        await self._respond(interaction, f"✅ DM inviato a **{user}** (`{user.id}`).")

    @commands.command(name="userinstallsync")
    @commands.is_owner()
    async def userinstallsync(self, ctx: commands.Context):
        """Sincronizza globalmente gli slash command del cog."""
        try:
            synced = await self.bot.tree.sync()
        except Exception as exc:
            return await ctx.send(f"Errore durante la sincronizzazione: `{exc}`")
        await ctx.send(f"Sincronizzazione globale completata: **{len(synced)}** comandi.")
