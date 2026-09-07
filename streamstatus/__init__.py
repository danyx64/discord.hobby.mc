from .streamstatus import StreamStatus


async def setup(bot):
    await bot.add_cog(StreamStatus(bot))
