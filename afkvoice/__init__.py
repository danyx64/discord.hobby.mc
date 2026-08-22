from .afkvoice import AFKVoice


async def setup(bot):
    await bot.add_cog(AFKVoice(bot))
