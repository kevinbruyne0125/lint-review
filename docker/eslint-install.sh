#!/bin/bash

# Check for /src/package.json if it doesn't exist exit.
if [ ! -e /src/package.json  ]; then
	exit 0
fi

cd /tool || exit 1

# Use grep & awk to find eslint packages.
while read -r package
do
	# Clean up the JSON into something we can put into npm install.
	package_name=$(echo "$package" | sed -e 's/,//' | sed -e 's/"//g' | sed -e 's/://' | awk '{print $1}')

	# Install required plugins into /tool/node_modules
	# Don't install all peerDeps as that can swap
	# eslint to a higher version that isn't tested.
	yarn add "$package_name"
done <  <(grep -i -E 'eslint-[plugin|config]-*' /src/package.json)

# Output the actual state of eslint packages.
while read -r package
do
	# Output installed packages for logging
	echo "add: $package"
done < <(yarn list --pattern 'eslint-[plugin|config]*')
