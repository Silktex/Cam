'use client';

import { Suspense, useRef, useMemo } from 'react';
import { Canvas, useFrame, useLoader } from '@react-three/fiber';
import { OrbitControls, Environment } from '@react-three/drei';
import * as THREE from 'three';

interface ThreePreviewProps {
  textureUrl: string;
  normalMapUrl?: string;
  roughnessMapUrl?: string;
  heightMapUrl?: string;
  geometry?: 'plane' | 'cylinder';
  roughness?: number;
  metalness?: number;
  tileRepeat?: [number, number];
}

function MaterialMesh({
  textureUrl,
  normalMapUrl,
  roughnessMapUrl,
  heightMapUrl,
  geometry = 'plane',
  roughness = 0.8,
  metalness = 0.0,
  tileRepeat = [2, 2],
}: ThreePreviewProps) {
  const meshRef = useRef<THREE.Mesh>(null);

  const albedoMap = useLoader(THREE.TextureLoader, textureUrl);
  const normalMap = normalMapUrl ? useLoader(THREE.TextureLoader, normalMapUrl) : null;
  const roughnessMap = roughnessMapUrl ? useLoader(THREE.TextureLoader, roughnessMapUrl) : null;

  useMemo(() => {
    const maps = [albedoMap, normalMap, roughnessMap].filter(Boolean) as THREE.Texture[];
    maps.forEach((map) => {
      map.wrapS = map.wrapT = THREE.RepeatWrapping;
      map.repeat.set(tileRepeat[0], tileRepeat[1]);
    });
  }, [albedoMap, normalMap, roughnessMap, tileRepeat]);

  // Slow rotation for visual feedback
  useFrame((_, delta) => {
    if (meshRef.current && geometry === 'cylinder') {
      meshRef.current.rotation.y += delta * 0.1;
    }
  });

  return (
    <mesh ref={meshRef} rotation={geometry === 'plane' ? [-Math.PI / 6, 0, 0] : [0, 0, 0]}>
      {geometry === 'plane' ? (
        <planeGeometry args={[4, 4, 64, 64]} />
      ) : (
        <cylinderGeometry args={[1.5, 1.5, 3, 64, 1, true]} />
      )}
      <meshStandardMaterial
        map={albedoMap}
        normalMap={normalMap || undefined}
        roughnessMap={roughnessMap || undefined}
        roughness={roughness}
        metalness={metalness}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

export default function ThreePreview(props: ThreePreviewProps) {
  return (
    <div className="w-full h-full min-h-[300px] rounded-xl overflow-hidden border border-slate-700/50 bg-slate-900">
      <Canvas
        camera={{ position: [0, 2, 4], fov: 50 }}
        gl={{ antialias: true }}
      >
        <ambientLight intensity={0.4} />
        <directionalLight position={[5, 5, 5]} intensity={1} />
        <directionalLight position={[-3, 2, -3]} intensity={0.3} />
        <Suspense fallback={null}>
          <MaterialMesh {...props} />
          <Environment preset="studio" />
        </Suspense>
        <OrbitControls
          enableDamping
          dampingFactor={0.05}
          minDistance={2}
          maxDistance={10}
        />
      </Canvas>
    </div>
  );
}
