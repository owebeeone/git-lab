

a collaborative work tool between 2 or more team members that allow for commands and inspection of each other's workspaces.


1. manage connections between peers - i.e. connection string + workspace root + OS type + tools avail (PS, bash etc)
2. The tool should be accessible from all collab machines via ssh forwarded ports
3. The tool will log all commands sent and executed to each machine with the results - akin to project_viewer.py - and stored in a folder (also git-ignored)
4. An additional workspace status view (one for each collabortator) akin to the graph view shown by project_viewer.py showing git status and other package details.
5. A chat tool that allows sharing of comments as well as links to command session so other collaborators can reference the same info. Session data should be stored on disk in a folder - one file per message. Files should be named so lexiographic order of file names are order of messages.
6. Allow for diff across workspaces - show which repos are at different checkout states or individual files with diffs.
7. Once a connection is made (one way) the server will allow for commands to be executed on any machine. This should also provide a tool for AI agents to execute commands on any collaborator via a permission gate by the destination collaborator.
8. gate means pop up or a persistent setting.
9. Architecture must be grip-react + python backend + interactive connections (WS)
10. unlike project-viewer, this should work on any root git repo with submodules - make no other assumptions.

UI Req.
1. On boarding UI - add collaborators - 
2. Workspace status (like project_viewer but react based.) with popover and onclick menu or tools for a repo - showing status on all collab repos
3. File viewer - this should create syntax highlighted text view of files
4. Diff file viewer - allows to select various versions of a file - local HEAD different collaborators local HEAD etc.
5. Chat - should be able to drag-drop file/repo/collaborator/command session reference so other collaborators can click and view.



