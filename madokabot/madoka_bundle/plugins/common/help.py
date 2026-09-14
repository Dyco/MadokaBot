from  .matchers import help_cmd
from ... import __plugin_meta__

@help_cmd.handle()
async def handle_help_base():
        await help_cmd.finish(__plugin_meta__.usage)
