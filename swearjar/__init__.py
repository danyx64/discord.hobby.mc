import re

import discord
from redbot.core import commands

from .swearjar import SwearJar


COMMAND_DESCRIPTIONS = {
    "swearjar": "Mostra i comandi e configura SwearJar.",
    "swearjar enable": "Abilita il rilevamento SwearJar nel server.",
    "swearjar disable": "Disabilita il rilevamento SwearJar nel server.",
    "swearjar status": "Mostra stato, regola, dizionari e configurazione canali.",
    "swearjar reloadfiles": "Ricarica divinita.txt e parolacce.txt dal disco.",
    "swearjar message": "Gestisce il messaggio inviato quando viene rilevata un'infrazione.",
    "swearjar message view": "Mostra il messaggio di risposta attuale.",
    "swearjar message set": "Imposta un nuovo messaggio di risposta.",
    "swearjar message reset": "Ripristina il messaggio di risposta predefinito.",
    "swearjar message usage": "Mostra i placeholder utilizzabili nel messaggio.",
    "swearjar deities": "Gestisce il dizionario delle divinita'.",
    "swearjar deities list": "Mostra tutte le divinita' configurate.",
    "swearjar deities add": "Aggiunge una divinita' al dizionario.",
    "swearjar deities remove": "Rimuove una divinita' dal dizionario.",
    "swearjar deities reset": "Ripristina il dizionario predefinito delle divinita'.",
    "swearjar profanities": "Gestisce il dizionario delle parolacce e degli insulti.",
    "swearjar profanities list": "Mostra tutte le parolacce configurate.",
    "swearjar profanities add": "Aggiunge una parola o frase al dizionario.",
    "swearjar profanities remove": "Rimuove una parola o frase dal dizionario.",
    "swearjar profanities reset": "Ripristina il dizionario predefinito delle parolacce.",
    "swearjar channels": "Configura in quali canali SwearJar deve funzionare.",
    "swearjar channels mode": "Imposta la modalita' canali: all, include oppure exclude.",
    "swearjar channels add": "Aggiunge un canale alla lista configurata.",
    "swearjar channels remove": "Rimuove un canale dalla lista configurata.",
    "swearjar channels list": "Mostra modalita' e canali configurati.",
    "leadswear": "Mostra la classifica Top 10 di SwearJar.",
}


async def setup(bot):
    cog = SwearJar(bot)
    await bot.add_cog(cog)

    parent = bot.get_command("swearjar")
    if parent is None:
        return

    # Aggiunge descrizioni a tutti i comandi gia' definiti nel cog.
    for command in bot.walk_commands():
        description = COMMAND_DESCRIPTIONS.get(command.qualified_name)
        if description:
            command.help = description
            command.brief = description

    # Il reset viene collegato al gruppo appena creato dal cog. Il controllo
    # evita registrazioni duplicate in caso di reload.
    if parent.get_command("reset") is None:
        async def reset_callback(ctx: commands.Context, *, target: str):
            """Azzera le statistiche di un utente, anche se ha lasciato il server."""
            value = target.strip()
            match = re.fullmatch(r"<@!?(\d{15,25})>", value)
            member = None

            if match:
                user_id = int(match.group(1))
                member = ctx.guild.get_member(user_id)
            elif value.isdigit() and 15 <= len(value) <= 25:
                user_id = int(value)
                member = ctx.guild.get_member(user_id)
            else:
                try:
                    member = await commands.MemberConverter().convert(ctx, value)
                    user_id = member.id
                except commands.BadArgument:
                    return await ctx.send(
                        "Utente non trovato. Se non e' piu' nel server usa il suo **ID Discord**.\n"
                        "Esempio: `[p]swear reset 123456789012345678`"
                    )

            member_group = cog.config.member_from_ids(ctx.guild.id, user_id)
            previous_count = await member_group.count()
            await member_group.count.set(0)

            if member is not None:
                label = member.mention
            else:
                try:
                    user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                    label = f"{user} (`{user_id}`)"
                except (discord.NotFound, discord.HTTPException):
                    label = f"utente `{user_id}`"

            await ctx.send(
                f"Statistiche SwearJar di {label} azzerate. "
                f"Conteggio precedente: **{previous_count}** -> **0**."
            )

        reset_command = commands.Command(
            reset_callback,
            name="reset",
            aliases=["resetstats", "resetbestemmie"],
            help="Azzera le statistiche di un utente, anche se ha lasciato il server.",
            brief="Azzera le statistiche di un utente.",
        )
        reset_command.guild_only = True
        reset_command.checks.append(commands.has_permissions(manage_guild=True).predicate)
        parent.add_command(reset_command)

    if parent.get_command("commands") is None:
        async def commands_callback(ctx: commands.Context):
            """Mostra la lista dei comandi SwearJar con una breve descrizione."""
            lines = []
            for command in sorted(parent.walk_commands(), key=lambda c: c.qualified_name):
                if command.hidden:
                    continue
                usage = command.qualified_name.replace("swearjar", "swear", 1)
                description = command.brief or command.short_doc or "Nessuna descrizione."
                lines.append(f"`{ctx.clean_prefix}{usage}` - {description}")

            text = "**Comandi SwearJar**\n" + "\n".join(lines)
            for start in range(0, len(text), 1900):
                await ctx.send(text[start:start + 1900])

        list_command = commands.Command(
            commands_callback,
            name="commands",
            aliases=["comandi", "help"],
            help="Mostra tutti i comandi SwearJar con la relativa descrizione.",
            brief="Mostra la lista dei comandi SwearJar.",
        )
        parent.add_command(list_command)
