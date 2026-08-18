import discord
from redbot.core import Config, commands


class LeavePlain(commands.Cog):
    """Avvisi testuali quando un membro lascia il server."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=64642026081801, force_registration=True
        )
        self.config.register_guild(
            channel_id=None,
            enabled=True,
            message="👋 È uscito {mention} | {name} | ID: {id}",
        )

    @commands.group(name="leaveplain", aliases=["lp"], invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def leaveplain(self, ctx):
        """Configura gli avvisi testuali per i membri che escono."""
        await ctx.send_help()

    async def _resolve_channel(self, ctx, channel_input: str):
        raw = channel_input.strip()

        if raw.startswith("<＃") and raw.endswith(">"):
            raw = raw[2:-1]
        elif raw.startswith("<#") and raw.endswith(">"):
            raw = raw[2:-1]

        try:
            channel_id = int(raw)
        except ValueError:
            channel = discord.utils.get(ctx.guild.text_channels, name=raw.lstrip("#"))
            return channel

        channel = ctx.guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel
        return None

    @leaveplain.command(name="canale", aliases=["channel", "ch"])
    async def canale(self, ctx, *, canale: str):
        """Imposta il canale tramite mention, nome oppure ID."""
        channel = await self._resolve_channel(ctx, canale)
        if channel is None:
            await ctx.send(
                "❌ **Canale non trovato.**\n"
                "Puoi usare una mention, il nome oppure l'ID numerico del canale.\n"
                "Esempi: `.lp canale #uscite` oppure `.lp canale 123456789012345678`"
            )
            return

        perms = channel.permissions_for(ctx.guild.me)
        if not perms.view_channel or not perms.send_messages:
            await ctx.send(
                f"❌ Ho trovato {channel.mention} (`{channel.id}`), ma non ho i permessi "
                "**Visualizza canale** e/o **Invia messaggi**."
            )
            return

        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(
            f"✅ **Canale delle uscite configurato correttamente.**\n"
            f"Canale: {channel.mention}\n"
            f"ID: `{channel.id}`\n"
            f"Puoi verificarlo con `.lp testcanale`."
        )

    @leaveplain.command(name="messaggio", aliases=["message", "msg"])
    async def messaggio(self, ctx, *, message: str):
        """Imposta il testo. Variabili: {mention}, {name}, {display_name}, {id}."""
        try:
            preview = message.format(
                mention="@Utente",
                name="utente",
                display_name="Utente",
                id="123456789",
            )
        except (KeyError, ValueError, IndexError):
            await ctx.send(
                "❌ **Messaggio non valido.** Usa solamente queste variabili: "
                "`{mention}`, `{name}`, `{display_name}`, `{id}`."
            )
            return

        await self.config.guild(ctx.guild).message.set(message)
        await ctx.send(
            "✅ **Messaggio aggiornato.**\n"
            f"Anteprima: {preview}\n"
            "Usa `.lp test` per provarlo nel canale configurato."
        )

    @leaveplain.command(name="attiva", aliases=["enable", "on"])
    async def attiva(self, ctx):
        """Attiva gli avvisi."""
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("✅ Avvisi di uscita **attivati**.")

    @leaveplain.command(name="disattiva", aliases=["disable", "off"])
    async def disattiva(self, ctx):
        """Disattiva gli avvisi."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("✅ Avvisi di uscita **disattivati**.")

    @leaveplain.command(name="mostra", aliases=["show", "config"])
    async def mostra(self, ctx):
        """Mostra la configurazione corrente."""
        data = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(data["channel_id"]) if data["channel_id"] else None
        stato = "✅ Attivi" if data["enabled"] else "⛔ Disattivati"
        channel_text = (
            f"{channel.mention} (`{channel.id}`)"
            if channel
            else (f"Canale non trovato (`{data['channel_id']}`)" if data["channel_id"] else "Non impostato")
        )
        await ctx.send(
            f"**Configurazione LeavePlain**\n"
            f"**Stato:** {stato}\n"
            f"**Canale:** {channel_text}\n"
            f"**Messaggio:** {data['message']}\n\n"
            "Alias rapido: `.lp`"
        )

    @leaveplain.command(name="testcanale", aliases=["testchannel", "tc"])
    async def testcanale(self, ctx, *, canale: str = None):
        """Verifica che il bot possa scrivere nel canale configurato o in un canale indicato."""
        if canale:
            channel = await self._resolve_channel(ctx, canale)
            if channel is None:
                await ctx.send("❌ Canale di test non trovato. Controlla mention, nome o ID.")
                return
        else:
            channel_id = await self.config.guild(ctx.guild).channel_id()
            if not channel_id:
                await ctx.send("❌ Nessun canale configurato. Usa `.lp canale <ID o #canale>`.")
                return
            channel = ctx.guild.get_channel(channel_id)
            if channel is None:
                await ctx.send(
                    f"❌ Il canale configurato con ID `{channel_id}` non esiste più o non è visibile al bot."
                )
                return

        perms = channel.permissions_for(ctx.guild.me)
        if not perms.view_channel:
            await ctx.send(f"❌ Non posso visualizzare {channel.mention} (`{channel.id}`).")
            return
        if not perms.send_messages:
            await ctx.send(f"❌ Posso vedere {channel.mention}, ma non posso inviare messaggi lì.")
            return

        try:
            await channel.send(
                f"✅ **Test LeavePlain riuscito.**\n"
                f"Canale configurato correttamente.\n"
                f"ID canale: `{channel.id}`"
            )
        except discord.Forbidden:
            await ctx.send("❌ Discord ha rifiutato l'invio: controlla i permessi del bot nel canale.")
            return
        except discord.HTTPException as exc:
            await ctx.send(f"❌ Errore Discord durante il test: `{exc}`")
            return

        await ctx.send(
            f"✅ **Test canale completato.** Il messaggio è stato inviato in {channel.mention} (`{channel.id}`)."
        )

    @leaveplain.command(name="test", aliases=["t"])
    async def test(self, ctx):
        """Invia un finto avviso di uscita usando il tuo account."""
        success, reason = await self._send_leave_message(ctx.guild, ctx.author, ignore_enabled=True)
        if success:
            channel_id = await self.config.guild(ctx.guild).channel_id()
            channel = ctx.guild.get_channel(channel_id)
            await ctx.send(
                f"✅ **Test uscita inviato correttamente** in {channel.mention} (`{channel.id}`)."
            )
        else:
            await ctx.send(f"❌ **Test non riuscito:** {reason}")

    async def _send_leave_message(self, guild, member, ignore_enabled=False):
        data = await self.config.guild(guild).all()
        if not ignore_enabled and not data["enabled"]:
            return False, "gli avvisi sono disattivati"
        if not data["channel_id"]:
            return False, "nessun canale è stato configurato"

        channel = guild.get_channel(data["channel_id"])
        if channel is None:
            return False, f"il canale con ID {data['channel_id']} non è stato trovato"

        try:
            text = data["message"].format(
                mention=member.mention,
                name=str(member),
                display_name=member.display_name,
                id=member.id,
            )
        except (KeyError, ValueError, IndexError):
            text = f"👋 È uscito {member.mention} | {member} | ID: {member.id}"

        try:
            await channel.send(
                text,
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False
                ),
            )
        except discord.Forbidden:
            return False, "non ho il permesso di inviare messaggi nel canale configurato"
        except discord.HTTPException as exc:
            return False, f"Discord ha restituito un errore: {exc}"
        return True, "ok"

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._send_leave_message(member.guild, member)
