from ... import __plugin_meta__
from .matchers import help_cmd


@help_cmd.handle()
async def handle_help_base():
    await help_cmd.finish(__plugin_meta__.usage)
